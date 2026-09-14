"""D1 public JSON acquisition probe. No evidence adoption or scoring."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

LIMIT = 20 * 1024 * 1024
HOSTS = {'data.sec.gov', 'www.sec.gov'}


def decode(raw):
    def reject_constant(value):
        raise ValueError('Nonstandard JSON number')
    return json.loads(raw, parse_constant=reject_constant)


def safe_url(url):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname not in HOSTS or p.username or p.password
            or p.port not in (None, 443) or p.query or p.fragment):
        raise ValueError('Only allowlisted public HTTPS URLs without query or credentials')
    return url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # A redirect must be reviewed; never forward a contact header.


def init(folder):
    folder = Path(folder).resolve()
    schema = Path(__file__).resolve().parents[2] / 'database/source_probe.sql'
    sql = schema.read_text(encoding='utf-8')
    folder.mkdir(exist_ok=False)
    with sqlite3.connect(folder / 'sources.sqlite') as db:
        db.executescript(sql)
    db.close()
    return {'path': str(folder), 'format': 'd1-public-json-v1'}


@contextmanager
def connect(folder):
    path = (Path(folder).resolve() / 'sources.sqlite').as_uri()
    db = sqlite3.connect(path + '?mode=rw', uri=True, timeout=5)
    try:
        if db.execute('SELECT format FROM identity').fetchall() != [('d1-public-json-v1',)]:
            raise ValueError('Wrong source probe store')
        yield db
    finally:
        db.close()


def capture(folder, url, user_agent=None, opener=None):
    safe_url(url)
    user_agent = user_agent or os.environ.get('SEC_USER_AGENT')
    raw, status, code, content_type, error = b'', 'success', None, '', None
    if not user_agent:
        status, error = 'configuration_required', 'Set SEC_USER_AGENT with your actual contact identification'
    else:
        try:
            req = Request(url, headers={'User-Agent': user_agent, 'Accept': 'application/json'})
            with (opener or build_opener(NoRedirect()).open)(req, timeout=30) as response:
                code = response.status
                if response.geturl() != url:
                    raise ValueError('Unexpected redirect')
                content_type = response.headers.get('Content-Type', '')
                raw = response.read(LIMIT + 1)
                if len(raw) > LIMIT:
                    raw, status, error = b'', 'partial', 'Response exceeds byte limit'
                elif not raw.strip():
                    status, error = 'parse_failed', 'Empty response'
                elif 'json' not in content_type.lower():
                    status, error = 'parse_failed', 'Expected JSON content type'
                else:
                    value = decode(raw)
                    if not isinstance(value, (dict, list)) or not value:
                        status, error = 'parse_failed', 'Expected nonempty JSON container'
        except HTTPError as exc:
            code = exc.code
            status = {403: 'forbidden', 404: 'not_found', 429: 'rate_limited',
                      401: 'auth_required'}.get(code, 'http_error')
            error = 'HTTP request failed'  # Never emit headers/contact information.
            exc.close()
        except (TimeoutError, socket.timeout):
            status, error = 'timeout', 'Request timed out'
        except URLError as exc:
            status = 'timeout' if isinstance(exc.reason, (TimeoutError, socket.timeout)) else 'network_error'
            error = 'Network request failed'
        except (ValueError, UnicodeError):
            status, error = 'parse_failed', 'Invalid JSON or unexpected response'
    sha = hashlib.sha256(raw).hexdigest() if raw else None
    document_id = hashlib.sha256((url + '\n' + str(sha)).encode()).hexdigest() if status == 'success' else None
    with connect(folder) as db, db:
        db.execute('BEGIN IMMEDIATE')
        if status == 'success':
            previous = db.execute('SELECT document_id FROM attempts WHERE url=? AND document_id IS NOT NULL ORDER BY id DESC LIMIT 1', (url,)).fetchone()
            if previous and previous[0] == document_id:
                status = 'unchanged'
            db.execute('INSERT OR IGNORE INTO documents VALUES (?,?,?,?)', (document_id, url, sha, raw))
        cur = db.execute('INSERT INTO attempts(url,at,status,http_status,content_type,document_id,error) VALUES (?,?,?,?,?,?,?)',
                         (url, datetime.now(timezone.utc).isoformat(), status, code, content_type, document_id, error))
        attempt = cur.lastrowid
    return {'attempt_id': attempt, 'status': status, 'document_id': document_id,
            'sha256': sha, 'bytes': len(raw), 'http_status': code, 'error': error}


def query(folder, document_id, pointer='', max_chars=12000):
    if not 1 <= max_chars <= 50000:
        raise ValueError('max_chars must be between 1 and 50000')
    with connect(folder) as db:
        row = db.execute('SELECT url,sha256,raw FROM documents WHERE id=?', (document_id,)).fetchone()
    if row is None:
        raise ValueError('Document not found; capture must succeed first')
    url, sha, raw = row
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError('Stored content hash mismatch')
    value = decode(raw)
    if pointer:
        if not pointer.startswith('/'):
            raise ValueError('Use a JSON Pointer beginning with /')
        for token in pointer[1:].split('/'):
            token = token.replace('~1', '/').replace('~0', '~')
            if isinstance(value, list):
                if not token.isdigit() or (len(token) > 1 and token.startswith('0')):
                    raise ValueError('Invalid list index')
                value = value[int(token)]
            else:
                value = value[token]
    text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    return {'document_id': document_id, 'source_url': url, 'sha256': sha,
            'json_pointer': pointer, 'total_chars': len(text),
            'truncated': len(text) > max_chars, 'preview': text[:max_chars],
            'warning': 'Raw JSON excerpt only; definitions, periods, units and counterevidence require review.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=['init', 'capture', 'query'])
    p.add_argument('--state-dir', required=True)
    p.add_argument('--url')
    p.add_argument('--document-id')
    p.add_argument('--pointer', default='')
    p.add_argument('--max-chars', type=int, default=12000)
    a = p.parse_args()
    try:
        if a.operation == 'init':
            result = init(a.state_dir)
        elif a.operation == 'capture':
            result = capture(a.state_dir, a.url or '')
        else:
            result = query(a.state_dir, a.document_id, a.pointer, a.max_chars)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('status', 'success') in ('success', 'unchanged') else 2
    except (ValueError, OSError, sqlite3.Error, KeyError, IndexError, TypeError):
        print(json.dumps({'status': 'error', 'error': 'Invalid input, missing data, or inaccessible store'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())

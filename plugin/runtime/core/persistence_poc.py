"""Portable, synthetic-only D1 probe. Not the production research schema."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import uuid

FORMAT = 'ai-bottleneck-synthetic-poc-v1'
SCHEMA = Path(__file__).resolve().parents[2] / 'database/poc_schema.sql'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def initialize(folder):
    """Exclusively reserve a new directory; never adopt an existing directory."""
    folder = Path(folder).resolve()
    folder.mkdir(parents=False, exist_ok=False)
    project = str(uuid.uuid4())
    db = sqlite3.connect(folder / 'poc.sqlite', isolation_level=None)
    try:
        with transaction(db):
            # This bundled schema has no triggers or semicolons in SQL literals.
            for statement in SCHEMA.read_text(encoding='utf-8').split(';'):
                if statement.strip():
                    db.execute(statement)
            db.execute('INSERT INTO identity VALUES (?, ?)', (project, FORMAT))
    finally:
        db.close()
    return {'project_id': project, 'path': str(folder), 'format': FORMAT}


@contextmanager
def connect(folder, project, timeout=3):
    path = (Path(folder).resolve() / 'poc.sqlite')
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True,
                         isolation_level=None, timeout=timeout)
    try:
        if db.execute('SELECT id, format FROM identity').fetchall() != [(project, FORMAT)]:
            raise ValueError('Project identity or POC format mismatch')
        if db.execute('SELECT version FROM migrations ORDER BY version').fetchall() != [(1,)]:
            raise ValueError('Unsupported POC schema version')
        yield db
    finally:
        db.close()


def validate(payload):
    if not isinstance(payload, dict) or payload.get('synthetic') is not True:
        raise ValueError('Only explicitly synthetic probe data is accepted')
    if payload.get('kind') not in ('node', 'source', 'evidence', 'event', 'score'):
        raise ValueError('Unsupported record kind')
    if not isinstance(payload.get('id'), str) or not payload['id'].strip():
        raise ValueError('A record id is required')
    canonical(payload)  # Reject NaN/Infinity and non-JSON values.


def append(folder, project, request_id, payload, timeout=3):
    validate(payload)
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError('A nonempty request id is required')
    body, sha = canonical(payload), digest(payload)
    with connect(folder, project, timeout) as db, transaction(db):
        existing = db.execute('SELECT payload, sha256 FROM records WHERE request_id=?',
                              (request_id,)).fetchone()
        if existing:
            if existing != (body, sha):
                raise ValueError('Request id reused with different content')
            return {'inserted': False, 'sha256': sha}
        previous = [json.loads(row[0]) for row in db.execute('SELECT payload FROM records')]
        keys = {(x['kind'], x['id']) for x in previous}
        if (payload['kind'], payload['id']) in keys:
            raise ValueError('Record id already exists; append a new revision id')
        refs = payload.get('refs', [])
        if not isinstance(refs, list):
            raise ValueError('refs must be a list')
        for ref in refs:
            if (not isinstance(ref, dict)
                    or not isinstance(ref.get('kind'), str)
                    or not isinstance(ref.get('id'), str)
                    or (ref['kind'], ref['id']) not in keys):
                raise ValueError('Unresolved probe reference')
        db.execute('INSERT INTO records(request_id,payload,sha256) VALUES (?,?,?)',
                   (request_id, body, sha))
    return {'inserted': True, 'sha256': sha}


def inspect(folder, project):
    with connect(folder, project) as db:
        db.execute('BEGIN')  # Consistent read snapshot during concurrent appends.
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity failure')
        rows = db.execute('SELECT seq, request_id, payload, sha256 FROM records ORDER BY seq').fetchall()
        records = []
        for seq, request, body, sha in rows:
            item = json.loads(body)
            validate(item)
            if digest(item) != sha:
                raise ValueError('Content hash mismatch')
            records.append({'seq': seq, 'request_id': request, 'payload': item, 'sha256': sha})
    return {'project_id': project, 'format': FORMAT, 'count': len(records),
            'records': records, 'state_hash': digest(records)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['init', 'inspect', 'append'])
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--project-id')
    parser.add_argument('--request-id')
    parser.add_argument('--payload-file')
    args = parser.parse_args()
    try:
        if args.operation == 'init':
            result = initialize(args.state_dir)
        elif not args.project_id:
            raise ValueError('--project-id is required')
        elif args.operation == 'inspect':
            result = inspect(args.state_dir, args.project_id)
        else:
            if not args.payload_file:
                raise ValueError('--payload-file is required')
            payload = json.loads(Path(args.payload_file).read_text(encoding='utf-8'))
            result = append(args.state_dir, args.project_id, args.request_id, payload)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

"""D3 append-only store. Explicit paths/identity; no implicit legacy migration."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

FORMAT = 'ai-bottleneck-research-v1'
KINDS = {'node', 'fact', 'evidence', 'event', 'judgment', 'assessment', 'report', 'task'}


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else dumps(value).encode()).hexdigest()


def required(value, *fields):
    for field in fields:
        if field not in value or value[field] is None or value[field] == '':
            raise ValueError('Missing field: ' + field)


def check_document(row):
    if row is None:
        raise ValueError('Document missing')
    source_id=digest({'url':row['url'],'producer':row['producer']})
    expected=digest({'source':source_id,'sha256':digest(row['raw']),
                     'mime':row['mime'],'metadata':json.loads(row['metadata'])})
    if source_id!=row['source_id'] or expected!=row['id'] or digest(row['raw'])!=row['sha256']:
        raise ValueError('Document bytes or provenance hash mismatch')


def check_record(row,value):
    expected=row['kind']+'-'+digest({'kind':row['kind'],'request':row['request_id'],'payload':value})[:32]
    if digest(value)!=row['sha256'] or row['id']!=expected:
        raise ValueError('Record identity or payload hash mismatch')


def create(folder, config):
    required(config, 'name', 'scope', 'as_of_date')
    from datetime import date
    date.fromisoformat(config['as_of_date'])
    config_text = dumps(config)
    schema = Path(__file__).resolve().parents[2] / 'database/research_v1.sql'
    sql = schema.read_text(encoding='utf-8')
    folder = Path(folder).resolve()
    folder.mkdir(exist_ok=False)
    project = str(uuid.uuid4())
    db = sqlite3.connect(folder / 'research.sqlite')
    try:
        db.executescript('BEGIN IMMEDIATE;\n' + sql)
        db.execute('INSERT INTO identity VALUES (?,?,?,?)', (project, FORMAT, 1, config_text))
        db.execute('INSERT INTO migrations VALUES (?,?,?)', (1, digest(sql.encode()), now()))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    manifest = {'project_id': project, 'format': FORMAT, 'schema_version': 1,
                'database': 'research.sqlite', 'config': config}
    (folder / 'project.json').write_text(dumps(manifest), encoding='utf-8')
    return manifest


class Store:
    def __init__(self, folder, project_id):
        self.folder = Path(folder).resolve()
        self.path = self.folder / 'research.sqlite'
        self.project_id = project_id
        with self.connection() as db:
            self.config = json.loads(db.execute('SELECT config FROM identity').fetchone()[0])

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            identity = db.execute('SELECT project_id,format,schema_version FROM identity').fetchall()
            if [tuple(x) for x in identity] != [(self.project_id, FORMAT, 1)]:
                raise ValueError('Project identity or schema mismatch')
            yield db
            if write:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def record(self, record_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM records WHERE id=?', (record_id,)).fetchone()
        if row is None:
            raise ValueError('Record not found: ' + record_id)
        value = json.loads(row['payload'])
        check_record(row,value)
        return dict(row, payload=value)

    def records(self, kind=None):
        with self.connection() as db:
            ids = db.execute('SELECT id FROM records WHERE (? IS NULL OR kind=?) ORDER BY rowid', (kind, kind)).fetchall()
        return [self.record(x['id']) for x in ids]

    def append(self, kind, request_id, payload, refs=(), documents=()):
        if kind not in KINDS or not isinstance(request_id, str) or not request_id.strip():
            raise ValueError('Invalid kind or request id')
        if not isinstance(payload, dict):
            raise ValueError('Payload must be an object')
        refs, documents = sorted(set(refs)), sorted(set(documents))
        envelope = {'data': payload, 'refs': refs, 'documents': documents}
        body = dumps(envelope)
        sha = digest(envelope)
        record_id = kind + '-' + digest({'kind': kind, 'request': request_id, 'payload': envelope})[:32]
        with self.connection(True) as db:
            previous = db.execute('SELECT id,kind,payload FROM records WHERE request_id=?', (request_id,)).fetchone()
            if previous:
                if previous['kind'] != kind or previous['payload'] != body:
                    raise ValueError('Conflicting request id; use a new revision request')
                return {'id': previous['id'], 'inserted': False}
            for ref in refs:
                if not db.execute('SELECT 1 FROM records WHERE id=?', (ref,)).fetchone():
                    raise ValueError('Unresolved record reference')
            for doc in documents:
                if not db.execute('SELECT 1 FROM documents WHERE id=?', (doc,)).fetchone():
                    raise ValueError('Unresolved document reference')
            db.execute('INSERT INTO records VALUES (?,?,?,?,?,?)', (record_id, kind, request_id, body, sha, now()))
            db.executemany('INSERT INTO links VALUES (?,?)', [(record_id, ref) for ref in refs])
            db.executemany('INSERT INTO record_documents VALUES (?,?)', [(record_id, doc) for doc in documents])
        return {'id': record_id, 'inserted': True}

    def capture(self, source, raw, mime, metadata, status='success', detail=None):
        required(source, 'url', 'producer')
        source_id = digest({'url':source['url'],'producer':source['producer']})
        doc = None
        if raw is not None:
            if not isinstance(raw, bytes) or not raw:
                raise ValueError('Document must contain bytes')
            doc = digest({'source': source_id, 'sha256': digest(raw), 'mime': mime, 'metadata': metadata})
        with self.connection(True) as db:
            previous = db.execute('SELECT document_id FROM attempts WHERE source_id=? AND document_id IS NOT NULL ORDER BY id DESC LIMIT 1', (source_id,)).fetchone()
            if doc:
                if status == 'success' and previous and previous[0] == doc:
                    status = 'unchanged'
                db.execute('INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?,?,?,?)',
                           (doc, source_id, source['url'], source['producer'], mime, digest(raw), raw, dumps(metadata)))
            db.execute('INSERT INTO attempts(source_id,at,status,document_id,detail) VALUES (?,?,?,?,?)',
                       (source_id, now(), status, doc, dumps(detail or {})))
        return {'source_id': source_id, 'document_id': doc, 'status': status}

    def document(self, doc):
        with self.connection() as db:
            row = db.execute('SELECT * FROM documents WHERE id=?', (doc,)).fetchone()
        check_document(row)
        return dict(row, metadata=json.loads(row['metadata']))

    def snapshot(self):
        with self.connection(True) as db:
            records = [dict(x) for x in db.execute('SELECT * FROM records ORDER BY rowid')]
            docs = [dict(x) for x in db.execute('SELECT id,url,producer,sha256,mime,metadata FROM documents ORDER BY id')]
            attempts = [dict(x) for x in db.execute('SELECT * FROM attempts ORDER BY id')]
            for row in records:
                row['payload'] = json.loads(row['payload'])
                check_record(row,row['payload'])
            for row in db.execute('SELECT * FROM documents'):
                check_document(row)
            value = {'project_id': self.project_id, 'config': self.config, 'records': records,
                     'documents': docs, 'attempts': attempts, 'contract_version': '1.0'}
            sid = digest(value)
            db.execute('INSERT OR IGNORE INTO snapshots VALUES (?,?,?)', (sid, dumps(value), now()))
        return {'snapshot_id': sid, **value}

    def read_snapshot(self, sid):
        with self.connection() as db:
            row = db.execute('SELECT payload FROM snapshots WHERE id=?', (sid,)).fetchone()
        if not row:
            raise ValueError('Snapshot missing')
        value = json.loads(row[0])
        if digest(value) != sid:
            raise ValueError('Snapshot hash mismatch')
        return {'snapshot_id': sid, **value}

    def backup(self, destination):
        destination = Path(destination).resolve()
        destination.mkdir(exist_ok=False)
        target = destination / 'research.sqlite'
        with self.connection() as db:
            out = sqlite3.connect(target)
            try:
                db.backup(out)
            finally:
                out.close()
        manifest = {'project_id': self.project_id, 'database': 'research.sqlite', 'format': FORMAT,
                    'schema_version': 1, 'sha256': digest(target.read_bytes()), 'created_at': now()}
        (destination / 'backup.json').write_text(dumps(manifest), encoding='utf-8')
        return manifest


def restore(backup, destination):
    import shutil
    backup, destination = Path(backup).resolve(), Path(destination).resolve()
    manifest = json.loads((backup / 'backup.json').read_text(encoding='utf-8'))
    source = backup / 'research.sqlite'
    if digest(source.read_bytes()) != manifest['sha256']:
        raise ValueError('Backup checksum mismatch')
    original = Store(backup, manifest['project_id'])
    with original.connection() as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Backup integrity failure')
    destination.mkdir(exist_ok=False)
    shutil.copy2(source, destination / 'research.sqlite')
    project = {'project_id': original.project_id, 'format': FORMAT, 'schema_version': 1,
               'database': 'research.sqlite', 'config': original.config}
    (destination / 'project.json').write_text(dumps(project), encoding='utf-8')
    return project

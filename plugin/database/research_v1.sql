-- D3 contract 1.0: append-only research records and immutable source versions.
CREATE TABLE identity (project_id TEXT PRIMARY KEY, format TEXT NOT NULL, schema_version INTEGER NOT NULL, config TEXT NOT NULL);
CREATE TABLE migrations (version INTEGER PRIMARY KEY, script_hash TEXT NOT NULL, applied_at TEXT NOT NULL);
CREATE TABLE documents (id TEXT PRIMARY KEY, source_id TEXT NOT NULL, url TEXT NOT NULL, producer TEXT NOT NULL, mime TEXT NOT NULL, sha256 TEXT NOT NULL, raw BLOB NOT NULL, metadata TEXT NOT NULL);
CREATE TABLE attempts (id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, at TEXT NOT NULL, status TEXT NOT NULL, document_id TEXT REFERENCES documents(id), detail TEXT NOT NULL);
CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, request_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE links (record_id TEXT NOT NULL REFERENCES records(id), target_id TEXT NOT NULL REFERENCES records(id), PRIMARY KEY(record_id,target_id));
CREATE TABLE record_documents (record_id TEXT NOT NULL REFERENCES records(id), document_id TEXT NOT NULL REFERENCES documents(id), PRIMARY KEY(record_id,document_id));
CREATE TABLE snapshots (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX records_kind ON records(kind);
CREATE INDEX attempts_source ON attempts(source_id,id);

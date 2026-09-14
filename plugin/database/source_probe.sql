-- D1 public JSON probe. No research score or approval tables.
CREATE TABLE identity (format TEXT NOT NULL);
INSERT INTO identity VALUES ('d1-public-json-v1');
CREATE TABLE documents (id TEXT PRIMARY KEY, url TEXT NOT NULL, sha256 TEXT NOT NULL, raw BLOB NOT NULL);
CREATE TABLE attempts (
    id INTEGER PRIMARY KEY, url TEXT NOT NULL, at TEXT NOT NULL,
    status TEXT NOT NULL, http_status INTEGER, content_type TEXT,
    document_id TEXT, error TEXT
);

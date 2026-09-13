-- D1 synthetic storage probe only. Not the production research schema.
CREATE TABLE identity (id TEXT PRIMARY KEY, format TEXT NOT NULL);
CREATE TABLE migrations (version INTEGER PRIMARY KEY);
INSERT INTO migrations VALUES (1);
CREATE TABLE records (
    seq INTEGER PRIMARY KEY,
    request_id TEXT UNIQUE NOT NULL,
    payload TEXT NOT NULL,
    sha256 TEXT NOT NULL
);

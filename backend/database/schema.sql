CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK( type IN ('credit', 'payment', 'correction', 'query', 'undo') ),
    customer_id TEXT,
    customer_name TEXT,
    amount REAL,
    date TEXT,
    confidence REAL,
    corrects TEXT,
    status TEXT NOT NULL CHECK( status IN ('committed', 'pending') ),
    meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_events_customer ON events(customer_name, date);
CREATE INDEX IF NOT EXISTS idx_events_corrects ON events(corrects);

def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fi_closings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            closed_by INTEGER REFERENCES users(id),
            closed_at TEXT,
            reopened_by INTEGER REFERENCES users(id),
            reopened_at TEXT,
            reopen_reason TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(year, month)
        )
    """)
    conn.commit()

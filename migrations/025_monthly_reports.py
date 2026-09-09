def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS monthly_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES client_companies(id),
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            data TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published')),
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(company_id, year, month)
        );
    """)

def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance_closings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            company_id INTEGER REFERENCES client_companies(id),
            status TEXT NOT NULL DEFAULT 'open',
            closed_by INTEGER REFERENCES users(id),
            closed_at TEXT,
            reopened_by INTEGER REFERENCES users(id),
            reopened_at TEXT,
            reopen_reason TEXT,
            absent_count INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(year, month, company_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance_closing_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            closing_id INTEGER NOT NULL REFERENCES attendance_closings(id),
            action TEXT NOT NULL,
            performed_by INTEGER NOT NULL REFERENCES users(id),
            reason TEXT DEFAULT '',
            detail TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_closing_logs_closing ON attendance_closing_logs(closing_id)"
    )

    try:
        conn.execute("ALTER TABLE users ADD COLUMN is_hr_admin INTEGER DEFAULT 0")
    except Exception:
        pass

    conn.commit()

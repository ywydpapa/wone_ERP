def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_prefs (
            user_id    INTEGER PRIMARY KEY REFERENCES users(id),
            widgets    TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()

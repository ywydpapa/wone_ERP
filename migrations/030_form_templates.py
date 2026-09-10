def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS form_templates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id  INTEGER NOT NULL,
            name        TEXT NOT NULL,
            category    TEXT DEFAULT '일반',
            fields      TEXT DEFAULT '[]',
            is_active   INTEGER DEFAULT 1,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        );
    """)

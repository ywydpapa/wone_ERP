def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS work_request_comments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id  INTEGER NOT NULL REFERENCES work_requests(id),
            user_id     INTEGER NOT NULL REFERENCES users(id),
            author      TEXT NOT NULL DEFAULT '',
            content     TEXT NOT NULL DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()

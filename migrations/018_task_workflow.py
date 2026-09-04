def up(conn):
    # 결과물
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_deliverables (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     INTEGER NOT NULL REFERENCES tasks(id),
            user_id     INTEGER NOT NULL REFERENCES users(id),
            file_name   TEXT DEFAULT '',
            file_path   TEXT DEFAULT '',
            comment     TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 댓글
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_comments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     INTEGER NOT NULL REFERENCES tasks(id),
            user_id     INTEGER NOT NULL REFERENCES users(id),
            author      TEXT NOT NULL DEFAULT '',
            content     TEXT NOT NULL DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 도움 요청
    conn.execute("""
        CREATE TABLE IF NOT EXISTS help_requests (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     INTEGER REFERENCES tasks(id),
            work_request_id INTEGER REFERENCES work_requests(id),
            employee_id INTEGER NOT NULL REFERENCES employees(id),
            reason      TEXT DEFAULT '',
            status      TEXT DEFAULT 'open' CHECK(status IN ('open','acknowledged','resolved')),
            resolved_by INTEGER REFERENCES users(id),
            resolve_note TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            resolved_at TEXT
        )
    """)

    conn.commit()

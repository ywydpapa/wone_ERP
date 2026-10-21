def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(work_requests)")}
    if "item_spec" not in cols:
        conn.execute("ALTER TABLE work_requests ADD COLUMN item_spec TEXT")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS work_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id  INTEGER NOT NULL REFERENCES work_requests(id),
            task_id     INTEGER REFERENCES tasks(id),
            seq         INTEGER NOT NULL,
            source      TEXT DEFAULT '',
            result      TEXT DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'open'
                        CHECK(status IN ('open','done','hold','approved','rejected')),
            hold_note   TEXT DEFAULT '',
            done_by     INTEGER REFERENCES employees(id),
            done_at     TEXT,
            sampled     INTEGER DEFAULT 0,
            round       INTEGER DEFAULT 0,
            reviewed_by INTEGER REFERENCES users(id),
            reviewed_at TEXT,
            review_note TEXT DEFAULT '',
            UNIQUE(request_id, seq)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_work_items_task_status
        ON work_items(task_id, status)
    """)
    conn.commit()

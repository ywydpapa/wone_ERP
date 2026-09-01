
def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_type TEXT NOT NULL,
            doc_id INTEGER NOT NULL,
            step INTEGER NOT NULL DEFAULT 1,
            approver_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            comment TEXT,
            acted_at TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_approvals_doc
        ON approvals (doc_type, doc_id)
    """)

    for row in conn.execute(
        "SELECT id, status, approved_by, approved_at, reject_reason FROM leave_requests"
    ).fetchall():
        a_status = 'approved' if row['status'] == 'approved' else (
            'rejected' if row['status'] == 'rejected' else 'pending'
        )
        conn.execute(
            """INSERT INTO approvals (doc_type, doc_id, step, approver_id, status, comment, acted_at)
               VALUES ('leave', ?, 1, ?, ?, ?, ?)""",
            (row['id'], row['approved_by'], a_status, row['reject_reason'], row['approved_at'])
        )

    conn.commit()

def get_approval(conn, doc_type, doc_id, step=1):
    return conn.execute(
        "SELECT * FROM approvals WHERE doc_type=? AND doc_id=? AND step=? ORDER BY id DESC LIMIT 1",
        (doc_type, doc_id, step)
    ).fetchone()


def get_approvals(conn, doc_type, doc_id):
    return conn.execute(
        "SELECT * FROM approvals WHERE doc_type=? AND doc_id=? ORDER BY step",
        (doc_type, doc_id)
    ).fetchall()


def create_approval(conn, doc_type, doc_id, step=1, approver_id=None):
    conn.execute(
        """INSERT INTO approvals (doc_type, doc_id, step, approver_id)
           VALUES (?, ?, ?, ?)""",
        (doc_type, doc_id, step, approver_id)
    )
    conn.commit()


def approve(conn, doc_type, doc_id, approver_id, step=1):
    conn.execute(
        """UPDATE approvals SET status='approved', approver_id=?, acted_at=datetime('now','localtime')
           WHERE doc_type=? AND doc_id=? AND step=? AND status='pending'""",
        (approver_id, doc_type, doc_id, step)
    )
    conn.commit()


def reject(conn, doc_type, doc_id, approver_id, comment='', step=1):
    conn.execute(
        """UPDATE approvals SET status='rejected', approver_id=?, comment=?, acted_at=datetime('now','localtime')
           WHERE doc_type=? AND doc_id=? AND step=? AND status='pending'""",
        (approver_id, doc_type, doc_id, step)
    )
    conn.commit()

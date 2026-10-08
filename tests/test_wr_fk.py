import sqlite3


def test_no_wr_old_reference(db):
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE sql LIKE '%_wr_old%'").fetchone()


def test_task_insert_with_fk_on(db_path, seed):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    wr = conn.execute("INSERT INTO work_requests (company_id, title, task_type, status) VALUES (?, '요청', 'erp', 'submitted')", (seed["a"]["company"],)).lastrowid
    conn.execute("INSERT INTO tasks (work_request_id, title, task_type) VALUES (?, '업무', 'erp')", (wr,))
    conn.execute("INSERT INTO work_request_comments (request_id, user_id) VALUES (?, ?)", (wr, seed["a"]["mgr"]))
    conn.close()

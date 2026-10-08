from datetime import timedelta

from core.tz import today_kst


def _emp_id(db, user_id):
    return db.execute("SELECT id FROM employees WHERE user_id=?", (user_id,)).fetchone()[0]


def _add_task(db, emp_id, title, status, due_date):
    db.execute(
        "INSERT INTO tasks (title, task_type, assigned_to, status, due_date) VALUES (?,?,?,?,?)",
        (title, "other", emp_id, status, due_date),
    )


def test_today_tab_shows_due_today_and_overdue(db, seed, login):
    emp_id = _emp_id(db, seed["a"]["wk"])
    today = today_kst().isoformat()
    yesterday = (today_kst() - timedelta(days=1)).isoformat()
    tomorrow = (today_kst() + timedelta(days=1)).isoformat()

    _add_task(db, emp_id, "오늘마감업무", "assigned", today)
    _add_task(db, emp_id, "연체업무", "in_progress", yesterday)
    _add_task(db, emp_id, "오늘완료업무", "completed", today)
    _add_task(db, emp_id, "내일업무", "assigned", tomorrow)
    _add_task(db, emp_id, "반려업무", "returned", today)
    _add_task(db, emp_id, "검토업무", "review", today)
    db.commit()

    html = login("a_wk").get("/my-tasks?status=today").text
    assert "오늘마감업무" in html
    assert "연체업무" in html
    assert "오늘완료업무" not in html
    assert "내일업무" not in html
    assert "반려업무" in html
    assert "검토업무" not in html

from core import accruals


def _accrual(db, book, **over):
    row = {"kind": "prepaid", "expense_code": "817", "amount": 1000, "start_ym": "2026-01", "end_ym": "2026-03",
           "partner_id": None, "dept": "", "memo": "", "status": "active", "created_by": None,
           "created_at": "2026-01-01 00:00:00"}
    row.update(over)
    row["id"] = db.execute(
        """INSERT INTO accruals (company_id, kind, expense_code, amount, start_ym, end_ym, partner_id, dept, memo,
               status, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (book, row["kind"], row["expense_code"], row["amount"], row["start_ym"], row["end_ym"], row["partner_id"],
         row["dept"], row["memo"], row["status"], row["created_by"], row["created_at"]),
    ).lastrowid
    return row


def _recurring(db, book, lines_json, **over):
    row = {"title": "임차료", "day": 0, "lines_json": lines_json, "start_ym": "2026-01", "end_ym": "2026-06",
           "status": "active", "created_by": None, "created_at": "2026-01-01 00:00:00"}
    row.update(over)
    row["id"] = db.execute(
        """INSERT INTO recurring_slips (company_id, title, day, lines_json, start_ym, end_ym, status,
               created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
        (book, row["title"], row["day"], lines_json, row["start_ym"], row["end_ym"], row["status"],
         row["created_by"], row["created_at"]),
    ).lastrowid
    return row


def test_monthly_split_with_remainder():
    amounts = accruals.monthly_amounts(1000, "2026-01", "2026-03")
    assert amounts == {"2026-01": 333, "2026-02": 333, "2026-03": 334}
    assert sum(amounts.values()) == 1000


def test_generate_accrual_idempotent(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    acc = _accrual(db, book)
    doc_id, err = accruals.post_accrual(db, book, uid, acc, "2026-01")
    assert err is None and doc_id
    assert db.execute("SELECT slip_total FROM erp_docs WHERE id=?", (doc_id,)).fetchone()[0] == 333

    # 같은 월 재생성 요청은 건너뜀
    doc_id2, err2 = accruals.post_accrual(db, book, uid, acc, "2026-01")
    assert doc_id2 is None and err2 is None
    cnt = db.execute(
        "SELECT COUNT(*) FROM erp_docs WHERE company_id=? AND source_type='accrual'", (book,)
    ).fetchone()[0]
    assert cnt == 1


def test_stopped_schedule_skipped(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    acc = _accrual(db, book, status="stopped")
    doc_id, err = accruals.post_accrual(db, book, uid, acc, "2026-01")
    assert doc_id is None and err is None
    assert db.execute("SELECT COUNT(*) FROM erp_docs WHERE company_id=?", (book,)).fetchone()[0] == 0


def test_closed_month_skipped_with_error(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    acc = _accrual(db, book)
    db.execute("INSERT INTO fi_closings (company_id, year, month, status) VALUES (?,2026,1,'closed')", (book,))
    doc_id, err = accruals.post_accrual(db, book, uid, acc, "2026-01")
    assert doc_id is None and err
    assert db.execute("SELECT COUNT(*) FROM accrual_posts WHERE accrual_id=?", (acc["id"],)).fetchone()[0] == 0


def test_recurring_month_end(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    import json
    lines = [{"code": "817", "debit": 500, "credit": 0}, {"code": "103", "debit": 0, "credit": 500}]
    sched = _recurring(db, book, json.dumps(lines), day=0)
    doc_id, err = accruals.post_recurring(db, book, uid, sched, "2026-02")
    assert err is None and doc_id
    slip_date = db.execute("SELECT slip_date FROM erp_docs WHERE id=?", (doc_id,)).fetchone()[0]
    assert slip_date == "2026-02-28"


def test_tenant_isolation(db, seed):
    a, b = seed["a"]["company"], seed["b"]["company"]
    _accrual(db, a)
    _accrual(db, b)
    created, skipped, errors = accruals.run_accruals(db, a, seed["a"]["mgr"], "2026-01")
    assert created == 1 and not errors
    assert db.execute(
        "SELECT COUNT(*) FROM accrual_posts ap JOIN accruals ac ON ac.id=ap.accrual_id WHERE ac.company_id=?", (b,)
    ).fetchone()[0] == 0

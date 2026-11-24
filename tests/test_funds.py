from core import books, funds
from tests.conftest import make_partner


def _bank(db, book, account_no="111", name="계좌1"):
    pid = db.execute(
        "INSERT INTO partners (company_id, code, name, kind, partner_type) VALUES (?,?,?,'finance','both')",
        (book, f"F{account_no}", f"국민 {name}"),
    ).lastrowid
    bid = db.execute(
        "INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code, partner_id) "
        "VALUES (?,'국민',?,?,'103',?)",
        (book, account_no, name, pid),
    ).lastrowid
    return bid, pid


def _partner(db, book, code, name, terms="", days=0):
    return make_partner(db, book, code, name, pay_terms=terms, pay_days=days)


def test_daily_funds_prev_balance_carry(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    _bank(db, book)

    books.post(db, book, uid, "2026-10-01", [{"code": "103", "debit": 500000}, {"code": "401", "credit": 500000}],
               "매출", "ship")
    books.post(db, book, uid, "2026-10-02", [{"code": "101", "debit": 50000}, {"code": "103", "credit": 50000}],
               "현금출금", "bank_txn")
    db.commit()

    data = funds.daily_funds(db, book, "2026-10-02")
    cash = next(r for r in data["rows"] if r["code"] == "101")
    bank = next(r for r in data["rows"] if r["code"] == "103")

    assert cash["prev"] == 0 and cash["in"] == 50000 and cash["out"] == 0 and cash["cur"] == 50000
    assert bank["prev"] == 500000 and bank["in"] == 0 and bank["out"] == 50000 and bank["cur"] == 450000
    assert data["totals"]["prev"] == 500000 and data["totals"]["cur"] == 500000

    # 당일 전표 내역에는 101/103 두 줄 모두 표시
    assert len(data["lines"]) == 2


def test_daily_funds_unassigned_bucket(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    _bank(db, book)
    books.post(db, book, uid, "2026-10-10",
               [{"code": "103", "debit": 20000, "partner_id": None}, {"code": "401", "credit": 20000}],
               "미지정입금", "ship", keep_lines=True)
    db.commit()

    data = funds.daily_funds(db, book, "2026-10-10")
    unassigned = next(r for r in data["rows"] if r["label"] == "계좌 미지정")
    bank = next(r for r in data["rows"] if r["code"] == "103" and r["label"] != "계좌 미지정")

    assert unassigned["in"] == 20000 and unassigned["cur"] == 20000
    assert bank["in"] == 0 and bank["cur"] == 0


def test_daily_funds_tenant_isolation(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    other = seed["b"]["company"]
    _bank(db, book)
    books.post(db, book, uid, "2026-10-01", [{"code": "103", "debit": 300000}, {"code": "401", "credit": 300000}],
               "매출", "ship")
    db.commit()

    data = funds.daily_funds(db, other, "2026-10-01")
    assert len(data["rows"]) == 1
    assert data["rows"][0]["code"] == "101"
    assert data["totals"]["cur"] == 0


def test_cash_plan_buckets(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    p_ar = _partner(db, book, "C1", "가고객", "days", 10)
    p_ap = _partner(db, book, "C2", "나업체", "days", 5)

    # 기초 자금(현금) 10,000
    books.post(db, book, uid, "2026-10-05", [{"code": "101", "debit": 10000}, {"code": "401", "credit": 10000}],
               "현금매출", "ship")

    # 외상매출금: 만기 2026-10-11 -> 연체, 만기 2026-10-30 -> 2주차
    books.post(db, book, uid, "2026-10-01",
               [{"code": "110", "debit": 100000, "partner_id": p_ar}, {"code": "401", "credit": 100000}],
               "매출1", "ship")
    books.post(db, book, uid, "2026-10-20",
               [{"code": "110", "debit": 50000, "partner_id": p_ar}, {"code": "401", "credit": 50000}],
               "매출2", "ship")

    # 외상매입금: 만기 2026-10-25 -> 1주차
    books.post(db, book, uid, "2026-10-20",
               [{"code": "818", "debit": 80000}, {"code": "251", "credit": 80000, "partner_id": p_ap}],
               "매입", "purchase")

    # 미지급금 잔액 60,000 -> 기준월 다음달(11월) 10일에 일괄 반영
    books.post(db, book, uid, "2026-10-15", [{"code": "813", "debit": 60000}, {"code": "254", "credit": 60000}],
               "복리후생비 미지급", "payroll")
    db.commit()

    db.execute(
        "INSERT INTO notes (company_id, kind, note_no, partner_id, amount, issue_date, due_date, status) "
        "VALUES (?,'recv','N1',?,30000,'2026-10-01','2026-10-25','held')", (book, p_ar))
    db.execute(
        "INSERT INTO notes (company_id, kind, note_no, partner_id, amount, issue_date, due_date, status) "
        "VALUES (?,'pay','N2',?,20000,'2026-10-01','2026-11-15','issued')", (book, p_ap))
    db.commit()

    data = funds.cash_plan(db, book, "2026-10-23", 3)
    rows = {r["label"]: r for r in data["rows"]}

    assert data["opening"] == 10000
    overdue = rows["연체"]
    assert overdue["in"] == 100000 and overdue["out"] == 0
    assert overdue["balance"] == 10000 + 100000

    week0 = data["rows"][1]
    assert week0["in"] == 30000 and week0["out"] == 80000

    week1 = data["rows"][2]
    assert week1["in"] == 50000 and week1["out"] == 0

    week2 = data["rows"][3]
    assert week2["out"] == 60000

    week3 = data["rows"][4]
    assert week3["out"] == 20000
    # 기말 예상 잔액: 10000+100000+30000-80000+50000-60000-20000
    assert week3["balance"] == 30000

    assert len(data["items"]) == 6
    assert sum(1 for it in data["items"] if it["overdue"]) == 1

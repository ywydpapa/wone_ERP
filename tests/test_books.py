import pytest

from core import books


def L(code, dr=0, cr=0, **kw):
    return {"code": code, "debit": dr, "credit": cr, **kw}


def test_book_of(db, seed):
    a = seed["a"]
    assert books.book_of(db, {"id": seed["staff"], "role": "platform_staff"}) == 0
    assert books.book_of(db, {"id": a["mgr"], "role": "client"}) == a["company"]
    assert books.book_of(db, {"id": a["wk"], "role": "worker"}) == a["company"]
    assert books.book_of(db, {"id": 99999, "role": "worker"}) is None


def test_slip_no_per_book_per_day(db, seed):
    a, b = seed["a"]["company"], seed["b"]["company"]
    assert books.next_slip_no(db, a, "2026-09-01") == "20260901-00001"
    assert books.next_slip_no(db, a, "2026-09-01") == "20260901-00002"
    assert books.next_slip_no(db, b, "2026-09-01") == "20260901-00001"
    assert books.next_slip_no(db, a, "2026-09-02") == "20260902-00001"


def test_check_lines(db, seed):
    a = seed["a"]["company"]
    b = seed["b"]["company"]
    pa = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('X','가',?)", (a,)).lastrowid
    pb = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('X','나',?)", (b,)).lastrowid
    ok = [L("110", 1000, partner_id=pa), L("401", cr=1000)]
    assert books.check_lines(db, a, ok) is None
    assert books.check_lines(db, a, [L("110", 1000, partner_id=pa), L("401", cr=900)])  # 차대 불일치
    assert books.check_lines(db, a, [L("110", 1000), L("401", cr=1000)])  # 거래처 필수
    assert books.check_lines(db, a, [L("110", 1000, partner_id=pb), L("401", cr=1000)])  # 타사 거래처
    assert books.check_lines(db, a, [L("999", 1000), L("401", cr=1000)])  # 없는 계정
    assert books.check_lines(db, a, [L("103", 1000, 1000), L("401", cr=1000)])  # 한 줄에 차대 동시
    assert books.check_lines(db, a, [L("103", 0), L("401")])  # 0원
    db.execute("UPDATE accounts SET is_active=0 WHERE company_id=? AND code='813'", (a,))
    assert books.check_lines(db, a, [L("813", 500), L("103", cr=500)])  # 비활성


def test_post_and_closed(db, seed):
    a = seed["a"]["company"]
    uid = seed["a"]["wk"]
    doc = books.post(db, a, uid, "2026-09-10", [L("813", 500), L("103", cr=500)], "통신비", "ship", 7)
    d = db.execute("SELECT * FROM erp_docs WHERE id=?", (doc,)).fetchone()
    assert d["status"] == "done" and d["company_id"] == a
    assert d["slip_no"] == "20260910-00001" and d["doc_number"] == d["slip_no"]
    assert d["source_type"] == "ship" and d["source_id"] == 7 and d["posted_at"]
    lines = db.execute("SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc,)).fetchall()
    assert [l["account_name"] for l in lines] == ["[813] 통신비", "[103] 보통예금"]
    assert db.execute("SELECT COUNT(*) FROM doc_history WHERE doc_id=?", (doc,)).fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM erp_activity_log WHERE target_id=? AND module='slip'", (doc,)).fetchone()[0] == 1
    db.execute("INSERT INTO fi_closings (company_id, year, month, status) VALUES (?,2026,9,'closed')", (a,))
    assert books.period_closed(db, a, "2026-09-30")
    assert not books.period_closed(db, seed["b"]["company"], "2026-09-30")
    with pytest.raises(ValueError):
        books.post(db, a, uid, "2026-09-11", [L("813", 500), L("103", cr=500)], "통신비", "manual")


def test_reverse(db, seed):
    a = seed["a"]["company"]
    uid = seed["a"]["wk"]
    doc = books.post(db, a, uid, "2026-09-10", [L("813", 500), L("103", cr=500)], "통신비", "manual")
    rev = books.reverse(db, doc, uid, "2026-09-12")
    r = db.execute("SELECT * FROM erp_docs WHERE id=?", (rev,)).fetchone()
    assert r["reversal_of"] == doc and r["source_type"] == "reverse" and r["status"] == "done"
    lines = db.execute("SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=? ORDER BY line_no", (rev,)).fetchall()
    assert [tuple(l) for l in lines] == [("813", 0, 500), ("103", 500, 0)]
    with pytest.raises(ValueError):
        books.reverse(db, doc, uid, "2026-09-12")  # 중복 역분개
    with pytest.raises(ValueError):
        books.reverse(db, rev, uid, "2026-09-12")  # 역분개의 역분개


def test_acct_group():
    assert books.acct_group("103") == "당좌자산"
    assert books.acct_group("120") == "재고자산"
    assert books.acct_group("206") == "유형자산"
    assert books.acct_group("255") == "유동부채"
    assert books.acct_group("401") == "매출"
    assert books.acct_group("813") == "판매관리비"
    assert books.acct_group("951") == "영업외비용"

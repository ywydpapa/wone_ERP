from core import books, deemed_interest
from tests.conftest import make_partner


def _partner(db, book, name="임원김"):
    return make_partner(db, book, code=name, name=name, partner_type="both")


def test_jeoksu_accumulates_across_days(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    pid = _partner(db, book)
    # 1/1 가지급금 100,000 지급. 12/31까지 그대로 유지 -> 365일 x 100,000
    books.post(db, book, uid, "2026-01-01",
               [{"code": "134", "debit": 100000, "credit": 0, "partner_id": pid, "summary": "가지급"},
                {"code": "103", "debit": 0, "credit": 100000, "partner_id": pid, "summary": "가지급"}],
               "가지급금 지급", "manual")
    db.commit()

    r = deemed_interest.calc(db, book, 2026, "4.6")
    row = r["rows"][0]
    assert row["jeoksu"] == 100000 * 365
    # 인정이자 = 적수 x 4.6% / 365, 원 미만 절사
    assert row["deemed"] == int(100000 * 365 * 4.6 / 100 / 365)
    assert row["deemed"] == 4600


def test_gasugeum_offsets_gajigeupgeum(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    pid = _partner(db, book)
    books.post(db, book, uid, "2026-01-01",
               [{"code": "134", "debit": 100000, "credit": 0, "partner_id": pid, "summary": "가지급"},
                {"code": "103", "debit": 0, "credit": 100000, "partner_id": pid, "summary": "가지급"}],
               "가지급금 지급", "manual")
    books.post(db, book, uid, "2026-01-01",
               [{"code": "103", "debit": 60000, "credit": 0, "partner_id": pid, "summary": "가수금"},
                {"code": "258", "debit": 0, "credit": 60000, "partner_id": pid, "summary": "가수금"}],
               "가수금 입금", "manual")
    db.commit()

    r = deemed_interest.calc(db, book, 2026, "4.6")
    row = r["rows"][0]
    # 가지급금 100,000 - 가수금 60,000 = 40,000 순액으로 365일 누적
    assert row["jeoksu"] == 40000 * 365


def test_offset_floor_zero(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    pid = _partner(db, book)
    books.post(db, book, uid, "2026-01-01",
               [{"code": "134", "debit": 50000, "credit": 0, "partner_id": pid, "summary": "가지급"},
                {"code": "103", "debit": 0, "credit": 50000, "partner_id": pid, "summary": "가지급"}],
               "가지급금 지급", "manual")
    books.post(db, book, uid, "2026-01-01",
               [{"code": "103", "debit": 80000, "credit": 0, "partner_id": pid, "summary": "가수금"},
                {"code": "258", "debit": 0, "credit": 80000, "partner_id": pid, "summary": "가수금"}],
               "가수금 입금", "manual")
    db.commit()

    r = deemed_interest.calc(db, book, 2026, "4.6")
    row = r["rows"][0]
    assert row["jeoksu"] == 0
    assert row["deemed"] == 0


def test_leap_year_uses_366_divisor(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    pid = _partner(db, book)
    books.post(db, book, uid, "2028-01-01",
               [{"code": "134", "debit": 100000, "credit": 0, "partner_id": pid, "summary": "가지급"},
                {"code": "103", "debit": 0, "credit": 100000, "partner_id": pid, "summary": "가지급"}],
               "가지급금 지급", "manual")
    db.commit()

    r = deemed_interest.calc(db, book, 2028, "4.6")
    row = r["rows"][0]
    assert r["divisor"] == 366
    assert row["jeoksu"] == 100000 * 366
    assert row["deemed"] == int(100000 * 366 * 4.6 / 100 / 366)


def test_booked_threshold(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    pid = _partner(db, book)
    books.post(db, book, uid, "2026-01-01",
               [{"code": "134", "debit": 1000000, "credit": 0, "partner_id": pid, "summary": "가지급"},
                {"code": "103", "debit": 0, "credit": 1000000, "partner_id": pid, "summary": "가지급"}],
               "가지급금 지급", "manual")
    # 인정이자 = 1,000,000 * 365 * 4.6% / 365 = 46,000. 회사 계상 이자 45,000 -> 차이 1,000 (5% 미만) -> 익금산입 없음
    books.post(db, book, uid, "2026-12-31",
               [{"code": "103", "debit": 45000, "credit": 0, "partner_id": pid, "summary": "이자"},
                {"code": "901", "debit": 0, "credit": 45000, "partner_id": pid, "summary": "이자"}],
               "이자수익", "manual")
    db.commit()

    r = deemed_interest.calc(db, book, 2026, "4.6")
    row = r["rows"][0]
    assert row["deemed"] == 46000
    assert row["booked"] == 45000
    assert row["diff"] == 1000
    assert row["add"] == 0

    # 계상 이자가 더 작아 차이가 5% 이상이면 익금산입 대상
    db.execute("UPDATE slip_lines SET credit=30000 WHERE account_code='901'")
    db.commit()
    r2 = deemed_interest.calc(db, book, 2026, "4.6")
    row2 = r2["rows"][0]
    assert row2["diff"] == 16000
    assert row2["add"] == 16000


def test_tenant_isolation(db, seed):
    a, b = seed["a"]["company"], seed["b"]["company"]
    uid_a = seed["a"]["mgr"]
    pid_a = _partner(db, a, "회사A임원")
    pid_b = _partner(db, b, "회사B임원")
    books.post(db, a, uid_a, "2026-01-01",
               [{"code": "134", "debit": 100000, "credit": 0, "partner_id": pid_a, "summary": "가지급"},
                {"code": "103", "debit": 0, "credit": 100000, "partner_id": pid_a, "summary": "가지급"}],
               "가지급금 지급", "manual")
    db.commit()

    r_a = deemed_interest.calc(db, a, 2026, "4.6")
    r_b = deemed_interest.calc(db, b, 2026, "4.6")
    assert len(r_a["rows"]) == 1
    assert len(r_b["rows"]) == 0
    assert pid_b != pid_a


def test_route_renders(db, seed, login):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    pid = _partner(db, book)
    books.post(db, book, uid, "2026-01-01",
               [{"code": "134", "debit": 100000, "credit": 0, "partner_id": pid, "summary": "가지급"},
                {"code": "103", "debit": 0, "credit": 100000, "partner_id": pid, "summary": "가지급"}],
               "가지급금 지급", "manual")
    db.commit()

    c = login("a_mgr")
    r = c.get("/tax/deemed-interest", params={"year": 2026})
    assert r.status_code == 200
    assert "임원김" in r.text

    r2 = c.get("/tax/deemed-interest", params={"year": 2026, "export": "csv"})
    assert r2.status_code == 200
    assert "4600" in r2.text

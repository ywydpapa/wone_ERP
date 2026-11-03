import pytest

from core import invoices
from routers.erp_sales import _create_ship_slip
from tests.conftest import csrf, make_partner


def _ship(db, book, uid, sid, amount, code="C1", tax_type="과세"):
    pid = make_partner(db, book, code=code, tax_type=tax_type)
    doc = _create_ship_slip(db, book, sid, f"SH-{sid}", amount, uid, "2026-09-20", pid)
    return db.execute("SELECT id FROM tax_invoices WHERE doc_id=?", (doc,)).fetchone()[0]


def test_migration_adds_amend_reason_column(db):
    cols = {r[1] for r in db.execute("PRAGMA table_info(tax_invoices)")}
    assert "amend_reason" in cols


def test_amend_missing_or_invalid_reason_rejected(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    orig = _ship(db, a, uid, 1, 10000)
    with pytest.raises(ValueError):
        invoices.amend(db, a, uid, orig, "2026-09-25", 8000, None)
    with pytest.raises(ValueError):
        invoices.amend(db, a, uid, orig, "2026-09-25", 8000, 9)


def test_amend_reason1_forces_orig_date(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    orig = _ship(db, a, uid, 1, 10000)
    mid = invoices.amend(db, a, uid, orig, "2026-12-01", 8000, 1)
    m = db.execute("SELECT issue_date, status, amend_reason FROM tax_invoices WHERE id=?", (mid,)).fetchone()
    assert (m["issue_date"], m["status"], m["amend_reason"]) == ("2026-09-20", "수정", 1)


def test_amend_reason4_cancels_regardless_of_posted_supply(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    orig = _ship(db, a, uid, 1, 10000)
    cid = invoices.amend(db, a, uid, orig, "2026-09-25", 9999, 4)
    c = db.execute("SELECT supply_amt, vat, status FROM tax_invoices WHERE id=?", (cid,)).fetchone()
    assert (c["supply_amt"], c["vat"], c["status"]) == (-10000, -1000, "취소")


def test_amend_reason6_cancels_and_forces_orig_date(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    orig = _ship(db, a, uid, 1, 10000)
    cid = invoices.amend(db, a, uid, orig, "2026-12-01", 9999, 6)
    c = db.execute("SELECT issue_date, supply_amt, status FROM tax_invoices WHERE id=?", (cid,)).fetchone()
    assert (c["issue_date"], c["supply_amt"], c["status"]) == ("2026-09-20", -10000, "취소")


def test_amend_reason3_rejects_when_not_lower(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    orig = _ship(db, a, uid, 1, 10000)
    with pytest.raises(ValueError):
        invoices.amend(db, a, uid, orig, "2026-09-25", 10000, 3)
    with pytest.raises(ValueError):
        invoices.amend(db, a, uid, orig, "2026-09-25", 12000, 3)
    mid = invoices.amend(db, a, uid, orig, "2026-09-25", 8000, 3)
    assert db.execute("SELECT status FROM tax_invoices WHERE id=?", (mid,)).fetchone()[0] == "수정"


def test_amend_reason5_requires_lc_fields(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    orig = _ship(db, a, uid, 1, 10000)
    with pytest.raises(ValueError):
        invoices.amend(db, a, uid, orig, "2026-12-01", 10000, 5)
    with pytest.raises(ValueError):
        invoices.amend(db, a, uid, orig, "2026-12-01", 10000, 5, "LC-001", "")


def test_reason5_deadline(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    orig = _ship(db, a, uid, 1, 10000)
    # 2026-09-20이 속한 과세기간은 7~12월. 종료일 12-31 + 25일 = 2027-01-25
    with pytest.raises(ValueError):
        invoices.amend(db, a, uid, orig, "2026-12-01", 10000, 5, "LC-001", "2027-01-26")


def test_amend_reason5_zero_rate_pair(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    orig = _ship(db, a, uid, 1, 10000)
    zid = invoices.amend(db, a, uid, orig, "2026-12-01", 10000, 5, "LC-001", "2026-10-15")
    c = db.execute("SELECT tax_type, supply_amt, vat, status, lc_no, lc_open_date FROM tax_invoices WHERE orig_id=?",
                  (orig,)).fetchone()
    assert (c["tax_type"], c["supply_amt"], c["vat"], c["status"]) == ("과세", -10000, -1000, "취소")
    assert (c["lc_no"], c["lc_open_date"]) == ("LC-001", "2026-10-15")
    z = db.execute("SELECT * FROM tax_invoices WHERE id=?", (zid,)).fetchone()
    assert (z["tax_type"], z["supply_amt"], z["vat"], z["status"], z["issue_date"], z["amend_reason"]) == \
        ("영세", 10000, 0, "정상", "2026-09-20", 5)
    assert (z["lc_no"], z["lc_open_date"]) == ("LC-001", "2026-10-15")
    assert z["remark"] == "내국신용장 개설일 2026-10-15 번호 LC-001"

    ret = invoices.vat_return(db, a, "2026-07-01", "2026-09-30")
    rows = {r[0]: r[1:] for r in ret["sales"]}
    assert rows["과세 세금계산서 발급분"][1:] == (0, 0)
    assert rows["영세율 세금계산서 발급분"][1] == 10000
    assert not ret["warns"]

    with pytest.raises(ValueError):
        invoices.amend(db, a, uid, orig, "2026-09-25", 10000, 2)
    mid = invoices.amend(db, a, uid, zid, "2026-09-25", 8000, 2)
    assert db.execute("SELECT vat FROM tax_invoices WHERE id=?", (mid,)).fetchone()[0] == 0

    exempt_orig = _ship(db, a, uid, 2, 10000, code="C2", tax_type="면세")
    with pytest.raises(ValueError):
        invoices.amend(db, a, uid, exempt_orig, "2026-09-25", 10000, 5)


def test_amend_reason2_no_extra_rule(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    orig = _ship(db, a, uid, 1, 10000)
    mid = invoices.amend(db, a, uid, orig, "2026-09-25", 12000, 2)
    m = db.execute("SELECT status, supply_amt, vat FROM tax_invoices WHERE id=?", (mid,)).fetchone()
    assert (m["status"], m["supply_amt"], m["vat"]) == ("수정", 2000, 200)


def test_detail_shows_reason_label(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    orig = _ship(db, a, uid, 1, 10000)
    mid = invoices.amend(db, a, uid, orig, "2026-09-25", 8000, 2)
    db.commit()
    c = login("a_mgr")
    r = c.get(f"/tax-invoices/{mid}")
    assert r.status_code == 200 and "공급가액 변동" in r.text
    r2 = c.get(f"/tax-invoices/{orig}")
    assert r2.status_code == 200 and "공급가액 변동" in r2.text


def test_route_amend_requires_reason(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    orig = _ship(db, a, uid, 1, 10000)
    db.commit()
    c = login("a_mgr")
    tok = csrf(c, f"/tax-invoices/{orig}")
    r = c.post(f"/tax-invoices/{orig}/amend", data={"csrf_token": tok, "issue_date": "2026-09-25", "supply": "8000"},
               follow_redirects=False)
    assert r.status_code == 303 and "error=" in r.headers["location"]
    assert db.execute("SELECT COUNT(*) FROM tax_invoices WHERE orig_id=?", (orig,)).fetchone()[0] == 0


def test_route_amend_with_reason(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    orig = _ship(db, a, uid, 1, 10000)
    db.commit()
    c = login("a_mgr")
    tok = csrf(c, f"/tax-invoices/{orig}")
    r = c.post(f"/tax-invoices/{orig}/amend",
               data={"csrf_token": tok, "issue_date": "2026-09-25", "supply": "8000", "reason": "2"},
               follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT amend_reason FROM tax_invoices WHERE orig_id=?", (orig,)).fetchone()
    assert row[0] == 2

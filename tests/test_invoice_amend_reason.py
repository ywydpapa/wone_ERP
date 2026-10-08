import pytest

from core import invoices
from routers.erp_sales import _create_ship_slip
from tests.conftest import csrf


def _partner(db, book, tax_type="과세", code="C1"):
    return db.execute(
        "INSERT INTO partners (code, name, company_id, tax_type) VALUES (?,?,?,?)",
        (code, f"거래처{code}", book, tax_type),
    ).lastrowid


def _ship(db, book, uid, sid, amount, code="C1", tax_type="과세"):
    doc = _create_ship_slip(db, book, sid, f"SH-{sid}", amount, uid, "2026-09-20", _partner(db, book, tax_type, code))
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


def test_amend_reason5_zeroes_vat_and_requires_taxed(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    orig = _ship(db, a, uid, 1, 10000)
    mid = invoices.amend(db, a, uid, orig, "2026-12-01", 10000, 5)
    m = db.execute("SELECT issue_date, supply_amt, vat, amend_reason FROM tax_invoices WHERE id=?", (mid,)).fetchone()
    assert (m["issue_date"], m["supply_amt"], m["vat"], m["amend_reason"]) == ("2026-09-20", 0, -1000, 5)

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

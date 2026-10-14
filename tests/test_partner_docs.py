from datetime import date

import core.tz
import routers.erp_accounting as erp_accounting
from core import books


def _mk_partner(db, cid, code, name, ptype="both", trade_status="active", pay_terms="", pay_days=0):
    return db.execute(
        """INSERT INTO partners (code, name, company_id, partner_type, trade_status, pay_terms, pay_days)
           VALUES (?,?,?,?,?,?,?)""",
        (code, name, cid, ptype, trade_status, pay_terms, pay_days),
    ).lastrowid


def _item(db, cid, code="I1", price=100000):
    return db.execute(
        "INSERT INTO items (item_code, item_name, unit_price, company_id) VALUES (?,?,?,?)",
        (code, "품목", price, cid),
    ).lastrowid


def _contact(db, cid, pid, name, roles, email="", is_active=1):
    return db.execute(
        """INSERT INTO partner_contacts (company_id, partner_id, name, roles, email, is_active)
           VALUES (?,?,?,?,?,?)""",
        (cid, pid, name, roles, email, is_active),
    ).lastrowid


def _quote(c, pid, item_id, qty=1, **extra):
    return c.post("/quotations/save", data={
        "qt_id": "0", "partner_id": str(pid), "quote_date": "2026-10-08",
        "line_nums": "1", "item_id_1": str(item_id), "qty_1": str(qty), "price_1": "100000", **extra,
    }, follow_redirects=False)


def _po(c, pid, item_id, qty=1, **extra):
    return c.post("/purchase-orders/save", data={
        "po_id": "0", "partner_id": str(pid), "po_date": "2026-10-08",
        "line_nums": "1", "item_id_1": str(item_id), "qty_1": str(qty), "price_1": "100000", **extra,
    }, follow_redirects=False)


def test_quote_save_blocked_trade_stop(db, seed, login):
    a = seed["a"]["company"]
    pid = _mk_partner(db, a, "C1", "중지거래처", trade_status="stop")
    item = _item(db, a)
    db.commit()
    r = _quote(login("a_mgr"), pid, item)
    assert r.status_code == 400
    assert "거래중지" in r.json()["notice"]
    assert db.execute("SELECT COUNT(*) FROM quotations").fetchone()[0] == 0


def test_quote_save_warn_hold_then_confirm(db, seed, login):
    a = seed["a"]["company"]
    pid = _mk_partner(db, a, "C2", "보류거래처", trade_status="hold")
    item = _item(db, a)
    db.commit()
    c = login("a_mgr")
    r = _quote(c, pid, item)
    assert r.status_code == 409
    assert "거래보류" in r.json()["confirm"]
    assert db.execute("SELECT COUNT(*) FROM quotations").fetchone()[0] == 0
    r2 = _quote(c, pid, item, credit_ok="1")
    assert r2.status_code == 303
    assert db.execute("SELECT COUNT(*) FROM quotations").fetchone()[0] == 1


def test_po_save_blocked_trade_stop(db, seed, login):
    a = seed["a"]["company"]
    pid = _mk_partner(db, a, "S1", "중지공급처", ptype="supplier", trade_status="stop")
    item = _item(db, a)
    db.commit()
    r = _po(login("a_mgr"), pid, item)
    assert r.status_code == 400
    assert "거래중지" in r.json()["notice"]
    assert db.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0] == 0


def test_quote_accept_blocked_trade_stop(db, seed, login):
    a = seed["a"]["company"]
    pid = _mk_partner(db, a, "C3", "거래처3")
    item = _item(db, a)
    db.commit()
    c = login("a_mgr")
    r = _quote(c, pid, item)
    assert r.status_code == 303
    qt_id = db.execute("SELECT id FROM quotations ORDER BY id DESC LIMIT 1").fetchone()[0]

    # 수락 전 거래중지로 전환되면 수주 생성 차단
    db.execute("UPDATE partners SET trade_status='stop' WHERE id=?", (pid,))
    db.commit()
    r2 = c.post(f"/quotations/{qt_id}/accept", follow_redirects=False)
    assert r2.status_code == 400
    assert "거래중지" in r2.json()["error"]
    assert db.execute("SELECT COUNT(*) FROM sales_orders WHERE quote_id=?", (qt_id,)).fetchone()[0] == 0


def test_contact_id_other_partner_stored_as_null(db, seed, login):
    a = seed["a"]["company"]
    pid = _mk_partner(db, a, "C4", "거래처4")
    other_pid = _mk_partner(db, a, "C5", "거래처5")
    other_contact = _contact(db, a, other_pid, "담당자", "sales")
    item = _item(db, a)
    db.commit()

    r = _quote(login("a_mgr"), pid, item, contact_id=str(other_contact))
    assert r.status_code == 303
    qt_id = db.execute("SELECT id FROM quotations ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert db.execute("SELECT contact_id FROM quotations WHERE id=?", (qt_id,)).fetchone()[0] is None


def test_quote_accept_copies_contact_and_ship_to(db, seed, login):
    a = seed["a"]["company"]
    pid = _mk_partner(db, a, "C6", "거래처6")
    contact = _contact(db, a, pid, "김담당", "sales")
    item = _item(db, a)
    db.commit()
    c = login("a_mgr")
    r = _quote(c, pid, item, contact_id=str(contact), ship_to="서울시 강남구 1번지")
    assert r.status_code == 303
    qt_id = db.execute("SELECT id FROM quotations ORDER BY id DESC LIMIT 1").fetchone()[0]
    row = db.execute("SELECT contact_id, ship_to FROM quotations WHERE id=?", (qt_id,)).fetchone()
    assert (row["contact_id"], row["ship_to"]) == (contact, "서울시 강남구 1번지")

    r2 = c.post(f"/quotations/{qt_id}/accept", follow_redirects=False)
    assert r2.status_code == 303
    so = db.execute("SELECT contact_id, ship_to FROM sales_orders WHERE quote_id=?", (qt_id,)).fetchone()
    assert (so["contact_id"], so["ship_to"]) == (contact, "서울시 강남구 1번지")


def test_tax_invoice_create_blocked_trade_stop(db, seed, login):
    a = seed["a"]["company"]
    pid = _mk_partner(db, a, "C7", "거래처7", trade_status="stop")
    db.commit()
    r = login("a_mgr").post("/tax-invoices", data={
        "kind": "매출", "tax_type": "과세", "evidence": "세금계산서", "issue_date": "2026-10-08",
        "partner_id": str(pid), "acct": "401", "pay": "110",
        "line_count": "1", "item_name_1": "품목", "item_qty_1": "1", "item_price_1": "10000",
        "item_supply_1": "10000", "item_vat_1": "1000",
    }, follow_redirects=False)
    assert r.status_code == 400
    assert "거래중지" in r.json()["notice"]
    assert db.execute("SELECT COUNT(*) FROM tax_invoices").fetchone()[0] == 0


def test_api_partners_email_from_tax_contact_and_excludes_merged(db, seed, login):
    a = seed["a"]["company"]
    pid = _mk_partner(db, a, "C8", "거래처8")
    db.execute("UPDATE partners SET email='old@x.kr' WHERE id=?", (pid,))
    _contact(db, a, pid, "세금계산서담당", "tax", email="tax@x.kr")
    merged_pid = _mk_partner(db, a, "C9", "합병거래처")
    db.execute("UPDATE partners SET merged_into=? WHERE id=?", (pid, merged_pid))
    db.commit()

    rows = login("a_mgr").get("/api/partners").json()
    row = next(r for r in rows if r["id"] == pid)
    assert row["email"] == "tax@x.kr"
    assert all(r["id"] != merged_pid for r in rows)


def test_aging_basis_due_eom_30(db, seed, login, monkeypatch):
    monkeypatch.setattr(core.tz, "today_kst", lambda: date(2026, 10, 15))
    monkeypatch.setattr(erp_accounting, "today_kst", core.tz.today_kst)

    a = seed["a"]["company"]
    wk = seed["a"]["wk"]
    # 월말기준(eom) 30일: 9/5 매출 -> 기준일 9/30 + 30일 = 10/30. 조회일 10/15는 아직 미도래
    pid = _mk_partner(db, a, "C10", "말일거래처", pay_terms="eom", pay_days=30)
    books.post(db, a, wk, "2026-09-05",
               [{"code": "110", "debit": 1_000_000, "credit": 0, "partner_id": pid},
                {"code": "401", "debit": 0, "credit": 1_000_000}],
               "9월 매출", "manual")
    db.commit()

    html = login("a_mgr").get("/ledger/aging?view=ar&basis=due").text
    assert "말일거래처" in html
    assert "1,000,000" in html

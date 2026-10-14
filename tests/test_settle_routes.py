from urllib.parse import quote

import pytest

from core import books, credit, settle
from tests.conftest import csrf


def L(code, dr=0, cr=0, **kw):
    return {"code": code, "debit": dr, "credit": cr, **kw}


@pytest.fixture
def ctx(db, seed):
    a = seed["a"]
    pid = db.execute("INSERT INTO partners (code, name, company_id, is_active) VALUES ('C1','가고객',?,1)",
                     (a["company"],)).lastrowid
    bank = db.execute("INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) "
                      "VALUES (?,'국민','111','운영','103')", (a["company"],)).lastrowid
    db.commit()
    return {"book": a["company"], "uid": a["mgr"], "pid": pid, "bank": bank}


def sale(db, c, day, amt, pid=None, book=None, uid=None):
    return books.post(db, book or c["book"], uid or c["uid"], day,
                      [L("110", amt, partner_id=pid or c["pid"]), L("401", cr=amt)], "매출", "ship")


def base_data(c, d1, amount=1000):
    return {"kind": "수금", "settle_date": "2026-10-10", "partner_id": c["pid"], "amount": str(amount),
           "method": "보통예금", "bank_account_id": c["bank"], "wht_type": "없음", "memo": "",
           f"alloc_{d1}": str(amount)}


def test_collect_create_reduces_remain(db, ctx, login):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    db.commit()
    c = login("a_wk")
    tok = csrf(c, "/settlements/new")
    data = base_data(ctx, d1)
    data["csrf_token"] = tok
    r = c.post("/settlements", data=data, follow_redirects=False)
    assert r.status_code == 303
    sid = db.execute("SELECT id FROM settlements").fetchone()[0]
    assert r.headers["location"] == f"/settlements/{sid}"
    info = credit.open_items(db, ctx["book"], "110", ctx["pid"]).get(ctx["pid"], {"items": []})
    assert info["items"] == []


def test_alloc_mismatch_returns_400(db, ctx, login):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    db.commit()
    c = login("a_wk")
    tok = csrf(c, "/settlements/new")
    data = base_data(ctx, d1, amount=1000)
    data[f"alloc_{d1}"] = "400"
    data["csrf_token"] = tok
    r = c.post("/settlements", data=data)
    assert r.status_code == 400
    assert "일치" in r.json()["error"]


def test_foreign_partner_404(db, ctx, seed, login):
    foreign_pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('X1','타사거래처',?)",
                            (seed["b"]["company"],)).lastrowid
    db.commit()
    c = login("a_wk")
    tok = csrf(c, "/settlements/new")
    data = {"kind": "수금", "settle_date": "2026-10-10", "partner_id": foreign_pid, "amount": "100",
           "method": "현금", "bank_account_id": "", "wht_type": "없음", "memo": "", "advance": "1",
           "csrf_token": tok}
    r = c.post("/settlements", data=data)
    assert r.status_code == 404


def test_foreign_charge_doc_404(db, ctx, seed, login):
    b_pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('B1','나고객',?)",
                       (seed["b"]["company"],)).lastrowid
    foreign_doc = sale(db, ctx, "2026-09-01", 1000, pid=b_pid, book=seed["b"]["company"], uid=seed["b"]["mgr"])
    db.commit()
    c = login("a_wk")
    tok = csrf(c, "/settlements/new")
    data = base_data(ctx, foreign_doc)
    data["csrf_token"] = tok
    r = c.post("/settlements", data=data)
    assert r.status_code == 404


def test_new_shows_open_items_and_wht_only_for_pay(db, ctx, login):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    db.commit()
    slip_no = db.execute("SELECT slip_no FROM erp_docs WHERE id=?", (d1,)).fetchone()[0]
    c = login("a_wk")
    r = c.get(f"/settlements/new?kind=수금&partner_id={ctx['pid']}")
    assert r.status_code == 200
    assert slip_no in r.text
    assert 'name="wht_type"' not in r.text

    r2 = c.get(f"/settlements/new?kind=지급&partner_id={ctx['pid']}")
    assert 'name="wht_type"' in r2.text


def test_list_and_detail_scoped_to_book(db, ctx, seed, login):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    sid = settle.create(db, ctx["book"], ctx["uid"],
                        {"kind": "수금", "settle_date": "2026-10-10", "partner_id": ctx["pid"], "amount": 1000,
                         "method": "보통예금", "bank_account_id": ctx["bank"], "wht_type": "없음", "memo": "",
                         "items": [(d1, 1000)], "advance": False})
    db.commit()
    c = login("a_wk")
    assert c.get("/settlements").status_code == 200
    assert c.get(f"/settlements/{sid}").status_code == 200

    b = login("b_mgr")
    assert b.get(f"/settlements/{sid}").status_code == 404


def test_cancel_requires_editor_and_restores_remain(db, ctx, login):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    sid = settle.create(db, ctx["book"], ctx["uid"],
                        {"kind": "수금", "settle_date": "2026-10-10", "partner_id": ctx["pid"], "amount": 1000,
                         "method": "보통예금", "bank_account_id": ctx["bank"], "wht_type": "없음", "memo": "",
                         "items": [(d1, 1000)], "advance": False})
    db.commit()

    wk = login("a_wk")
    tok = csrf(wk, f"/settlements/{sid}")
    r = wk.request("DELETE", f"/settlements/{sid}", data={"csrf_token": tok})
    assert r.status_code == 403

    mgr = login("a_mgr")
    tok2 = csrf(mgr, f"/settlements/{sid}")
    r2 = mgr.request("DELETE", f"/settlements/{sid}", data={"csrf_token": tok2})
    assert r2.status_code == 200
    assert db.execute("SELECT canceled_at FROM settlements WHERE id=?", (sid,)).fetchone()[0]
    remain = credit.open_items(db, ctx["book"], "110", ctx["pid"])[ctx["pid"]]["items"][0]["remain"]
    assert remain == 1000


def test_slip_entry_preset_redirects_to_settlement_new(db, ctx, login):
    c = login("a_wk")
    r = c.get(f"/slip_entry?partner_id={ctx['pid']}&kind=수금", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/settlements/new?kind={quote('수금')}&partner_id={ctx['pid']}"


def test_manual_reverse_blocked_for_settlement_slip(db, ctx, login):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    sid = settle.create(db, ctx["book"], ctx["uid"],
                        {"kind": "수금", "settle_date": "2026-10-10", "partner_id": ctx["pid"], "amount": 1000,
                         "method": "보통예금", "bank_account_id": ctx["bank"], "wht_type": "없음", "memo": "",
                         "items": [(d1, 1000)], "advance": False})
    db.commit()
    doc_id = db.execute("SELECT doc_id FROM settlements WHERE id=?", (sid,)).fetchone()[0]

    c = login("a_mgr")
    tok = csrf(c, "/slip_entry")
    r = c.post(f"/api/slip/{doc_id}/reverse", data={"csrf_token": tok, "slip_date": "2026-10-11"})
    assert r.status_code == 400
    assert "수금/지급 화면" in r.json()["error"]


def test_bank_txn_link_marks_processed(db, ctx, login):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    tid = db.execute("INSERT INTO bank_txns (company_id, bank_account_id, txn_at, amt_in, hash, uploaded_at) "
                     "VALUES (?,?,'2026-10-10',1000,'h1','2026-10-10')", (ctx["book"], ctx["bank"])).lastrowid
    db.commit()
    c = login("a_wk")

    r0 = c.get(f"/settlements/new?kind=수금&partner_id={ctx['pid']}&bank_txn_id={tid}")
    assert r0.status_code == 200
    assert f'value="{tid}"' in r0.text

    tok = csrf(c, "/settlements/new")
    data = base_data(ctx, d1)
    data["bank_txn_id"] = str(tid)
    data["csrf_token"] = tok
    r = c.post("/settlements", data=data, follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT status FROM bank_txns WHERE id=?", (tid,)).fetchone()[0] == "처리"


def test_bank_txn_missing_is_404(db, ctx, login):
    c = login("a_wk")
    r = c.get(f"/settlements/new?kind=수금&partner_id={ctx['pid']}&bank_txn_id=99999")
    assert r.status_code == 404

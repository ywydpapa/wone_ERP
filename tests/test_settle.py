import pytest

from core import books, credit, settle


def L(code, dr=0, cr=0, **kw):
    return {"code": code, "debit": dr, "credit": cr, **kw}


@pytest.fixture
def ctx(db, seed):
    a, b = seed["a"], seed["b"]
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('C1','가고객',?)",
                     (a["company"],)).lastrowid
    other = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('C1','나고객',?)",
                       (b["company"],)).lastrowid
    bank = db.execute("INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) "
                      "VALUES (?,'국민','111','운영','103')", (a["company"],)).lastrowid
    return {"book": a["company"], "uid": a["mgr"], "pid": pid, "other": other, "bank": bank,
            "b_book": b["company"], "b_uid": b["mgr"]}


def sale(db, c, day, amt, pid=None, book=None, uid=None):
    return books.post(db, book or c["book"], uid or c["uid"], day,
                      [L("110", amt, partner_id=pid or c["pid"]), L("401", cr=amt)], "매출", "ship")


def buy(db, c, day, amt):
    return books.post(db, c["book"], c["uid"], day, [L("120", amt), L("251", cr=amt, partner_id=c["pid"])],
                      "매입", "gr")


def form(c, items, amount=None, **kw):
    f = {"kind": "수금", "settle_date": "2026-10-10", "partner_id": c["pid"], "method": "보통예금",
         "bank_account_id": c["bank"], "wht_type": "없음", "memo": "", "items": items, "advance": False}
    f["amount"] = sum(a for _, a in items) if amount is None else amount
    f.update(kw)
    return f


def remains(db, c, acct="110"):
    info = credit.open_items(db, c["book"], acct, c["pid"]).get(c["pid"], {"items": []})
    return {it["doc_id"]: it["remain"] for it in info["items"]}


def test_items_are_docs_oldest_first(db, ctx):
    d2 = sale(db, ctx, "2026-09-05", 2000)
    d1 = sale(db, ctx, "2026-09-01", 1000)
    items = credit.open_items(db, ctx["book"], "110", ctx["pid"])[ctx["pid"]]["items"]
    assert [it["doc_id"] for it in items] == [d1, d2]
    assert items[0]["slip_no"].startswith("20260901") and items[0]["charge"] == 1000


def test_settle_partial_and_slip(db, ctx):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    sid = settle.create(db, ctx["book"], ctx["uid"], form(ctx, [(d1, 400)]))
    assert remains(db, ctx) == {d1: 600}
    s = db.execute("SELECT * FROM settlements WHERE id=?", (sid,)).fetchone()
    lines = db.execute("SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=? ORDER BY line_no",
                       (s["doc_id"],)).fetchall()
    assert [tuple(r) for r in lines] == [("103", 400, 0), ("110", 0, 400)]
    assert db.execute("SELECT source_type FROM erp_docs WHERE id=?", (s["doc_id"],)).fetchone()[0] == "settlement"


def test_alloc_must_match_amount(db, ctx):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    with pytest.raises(ValueError, match="일치"):
        settle.create(db, ctx["book"], ctx["uid"], form(ctx, [(d1, 400)], amount=500))


def test_over_remain_rejected(db, ctx):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    settle.create(db, ctx["book"], ctx["uid"], form(ctx, [(d1, 800)]))
    with pytest.raises(ValueError, match="초과"):
        settle.create(db, ctx["book"], ctx["uid"], form(ctx, [(d1, 300)]))


def test_other_company_doc_not_found(db, ctx):
    foreign = sale(db, ctx, "2026-09-01", 1000, pid=ctx["other"], book=ctx["b_book"], uid=ctx["b_uid"])
    with pytest.raises(LookupError):
        settle.create(db, ctx["book"], ctx["uid"], form(ctx, [(foreign, 1000)]))


def test_wht_truncation():
    assert settle.calc_wht("사업소득", 1234567) == (37030, 3700)
    assert settle.calc_wht("기타소득", 1234567) == (98760, 9870)
    assert settle.calc_wht("없음", 1234567) == (0, 0)


def test_pay_with_wht(db, ctx):
    d1 = buy(db, ctx, "2026-09-01", 1000000)
    sid = settle.create(db, ctx["book"], ctx["uid"],
                        form(ctx, [(d1, 1000000)], kind="지급", wht_type="사업소득"))
    s = db.execute("SELECT * FROM settlements WHERE id=?", (sid,)).fetchone()
    assert s["wht_amt"] == 33000
    lines = db.execute("SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=? ORDER BY line_no",
                       (s["doc_id"],)).fetchall()
    assert [tuple(r) for r in lines] == [("103", 0, 967000), ("251", 1000000, 0), ("253", 0, 30000),
                                        ("253", 0, 3000)]
    assert remains(db, ctx, "251") == {}


def test_cancel_restores_remain(db, ctx):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    sid = settle.create(db, ctx["book"], ctx["uid"], form(ctx, [(d1, 1000)]))
    assert remains(db, ctx) == {}
    settle.cancel(db, ctx["book"], ctx["uid"], sid)
    assert remains(db, ctx) == {d1: 1000}
    s = db.execute("SELECT canceled_at, cancel_doc_id FROM settlements WHERE id=?", (sid,)).fetchone()
    assert s["canceled_at"] and s["cancel_doc_id"]
    with pytest.raises(ValueError):
        settle.cancel(db, ctx["book"], ctx["uid"], sid)


def test_closed_month_rejected(db, ctx):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    sid = settle.create(db, ctx["book"], ctx["uid"], form(ctx, [(d1, 1000)], settle_date="2026-09-20"))
    db.execute("INSERT INTO fi_closings (company_id, year, month, status, closed_by) VALUES (?,2026,9,'closed',?)",
               (ctx["book"], ctx["uid"]))
    with pytest.raises(ValueError, match="마감"):
        settle.create(db, ctx["book"], ctx["uid"], form(ctx, [], amount=100, settle_date="2026-09-25",
                                                         advance=True))
    with pytest.raises(ValueError, match="마감"):
        settle.cancel(db, ctx["book"], ctx["uid"], sid)


def test_legacy_offset_fifo(db, ctx):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    d2 = sale(db, ctx, "2026-09-02", 1000)
    books.post(db, ctx["book"], ctx["uid"], "2026-09-03", [L("103", 1500), L("110", cr=1500, partner_id=ctx["pid"])],
               "수기 수금", "manual")
    assert remains(db, ctx) == {d2: 500}
    settle.create(db, ctx["book"], ctx["uid"], form(ctx, [(d2, 200)]))
    assert remains(db, ctx) == {d2: 300}


def test_reversed_charge_drops(db, ctx):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    books.reverse(db, d1, ctx["uid"], "2026-09-02")
    assert remains(db, ctx) == {}


def test_advance_then_apply(db, ctx):
    settle.create(db, ctx["book"], ctx["uid"], form(ctx, [], amount=700, advance=True))
    assert settle.advance_balance(db, ctx["book"], "수금", ctx["pid"]) == 700
    d1 = sale(db, ctx, "2026-10-11", 1000)
    with pytest.raises(ValueError, match="부족"):
        settle.create(db, ctx["book"], ctx["uid"], form(ctx, [(d1, 800)], method="충당"))
    settle.create(db, ctx["book"], ctx["uid"], form(ctx, [(d1, 700)], method="충당"))
    assert remains(db, ctx) == {d1: 300}
    assert settle.advance_balance(db, ctx["book"], "수금", ctx["pid"]) == 0


def test_bank_txn_link(db, ctx):
    d1 = sale(db, ctx, "2026-09-01", 1000)
    tid = db.execute("INSERT INTO bank_txns (company_id, bank_account_id, txn_at, amt_in, hash, uploaded_at) "
                     "VALUES (?,?,'2026-10-10',1000,'h1','2026-10-10')", (ctx["book"], ctx["bank"])).lastrowid
    sid = settle.create(db, ctx["book"], ctx["uid"], form(ctx, [(d1, 1000)], bank_txn_id=tid))
    t = db.execute("SELECT status, settlement_id FROM bank_txns WHERE id=?", (tid,)).fetchone()
    assert tuple(t) == ("처리", sid)
    with pytest.raises(ValueError, match="이미 처리"):
        settle.create(db, ctx["book"], ctx["uid"], form(ctx, [], amount=10, advance=True, bank_txn_id=tid))
    settle.cancel(db, ctx["book"], ctx["uid"], sid)
    assert db.execute("SELECT status FROM bank_txns WHERE id=?", (tid,)).fetchone()[0] == "미처리"

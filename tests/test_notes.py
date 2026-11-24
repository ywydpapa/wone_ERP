import pytest

from core import books, credit, notes


@pytest.fixture
def ctx(db, seed):
    a, b = seed["a"], seed["b"]
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('C1','가고객',?)",
                     (a["company"],)).lastrowid
    endorsee = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('C2','나업체',?)",
                          (a["company"],)).lastrowid
    bank = db.execute("INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) "
                      "VALUES (?,'국민','111','운영','103')", (a["company"],)).lastrowid
    return {"book": a["company"], "uid": a["mgr"], "pid": pid, "endorsee": endorsee, "bank": bank,
            "b_book": b["company"], "b_uid": b["mgr"]}


def sale(db, c, day, amt):
    return books.post(db, c["book"], c["uid"], day,
                      [{"code": "110", "debit": amt, "partner_id": c["pid"]}, {"code": "401", "credit": amt}],
                      "매출", "ship")


def lines_of(db, doc_id):
    return [(r["account_code"], r["debit"], r["credit"]) for r in db.execute(
        "SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
    ).fetchall()]


def recv_form(c, **kw):
    f = {"partner_id": c["pid"], "amount": 100000, "note_no": "N1",
         "issue_date": "2026-10-01", "due_date": "2026-11-01", "bank": "국민은행", "is_electronic": False,
         "memo": ""}
    f.update(kw)
    return f


def test_receive(db, ctx):
    sale(db, ctx, "2026-09-01", 100000)
    nid = notes.receive(db, ctx["book"], ctx["uid"], recv_form(ctx))
    n = db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    assert n["status"] == "held" and n["kind"] == "recv"
    assert lines_of(db, n["issue_doc_id"]) == [("111", 100000, 0), ("110", 0, 100000)]


def test_collect(db, ctx):
    nid = notes.receive(db, ctx["book"], ctx["uid"], recv_form(ctx))
    doc_id = notes.collect(db, ctx["book"], ctx["uid"], nid, "2026-11-01", ctx["bank"])
    n = db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    assert n["status"] == "collected"
    assert lines_of(db, doc_id) == [("103", 100000, 0), ("111", 0, 100000)]


def test_discount_fee_to_956(db, ctx):
    nid = notes.receive(db, ctx["book"], ctx["uid"], recv_form(ctx))
    doc_id = notes.discount(db, ctx["book"], ctx["uid"], nid, "2026-10-15", ctx["bank"], 3000)
    n = db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    assert n["status"] == "discounted"
    assert lines_of(db, doc_id) == [("103", 97000, 0), ("956", 3000, 0), ("111", 0, 100000)]


def test_endorse_to_251(db, ctx):
    nid = notes.receive(db, ctx["book"], ctx["uid"], recv_form(ctx))
    doc_id = notes.endorse(db, ctx["book"], ctx["uid"], nid, "2026-10-20", ctx["endorsee"])
    n = db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    assert n["status"] == "endorsed" and n["endorsee_id"] == ctx["endorsee"]
    assert lines_of(db, doc_id) == [("251", 100000, 0), ("111", 0, 100000)]


def test_dishonor_to_246(db, ctx):
    nid = notes.receive(db, ctx["book"], ctx["uid"], recv_form(ctx))
    doc_id = notes.dishonor(db, ctx["book"], ctx["uid"], nid, "2026-11-02")
    n = db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    assert n["status"] == "dishonored"
    assert lines_of(db, doc_id) == [("246", 100000, 0), ("111", 0, 100000)]


def test_issue_pay(db, ctx):
    nid = notes.issue(db, ctx["book"], ctx["uid"],
                      {"partner_id": ctx["pid"], "amount": 50000, "note_no": "P1",
                       "issue_date": "2026-10-01", "due_date": "2026-12-01", "bank": "", "memo": ""})
    n = db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    assert n["kind"] == "pay" and n["status"] == "issued"
    assert lines_of(db, n["issue_doc_id"]) == [("251", 50000, 0), ("252", 0, 50000)]

    doc_id = notes.pay(db, ctx["book"], ctx["uid"], nid, "2026-12-01", ctx["bank"])
    n = db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    assert n["status"] == "paid"
    assert lines_of(db, doc_id) == [("252", 50000, 0), ("103", 0, 50000)]


def test_cancel_action_reverts_status(db, ctx):
    nid = notes.receive(db, ctx["book"], ctx["uid"], recv_form(ctx))
    notes.collect(db, ctx["book"], ctx["uid"], nid, "2026-11-01", ctx["bank"])
    notes.cancel(db, ctx["book"], ctx["uid"], nid)
    n = db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    assert n["status"] == "held" and n["close_doc_id"] is None


def test_cancel_receipt_itself(db, ctx):
    nid = notes.receive(db, ctx["book"], ctx["uid"], recv_form(ctx))
    notes.cancel(db, ctx["book"], ctx["uid"], nid)
    n = db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    assert n["status"] == "canceled"
    with pytest.raises(ValueError, match="이미 취소"):
        notes.cancel(db, ctx["book"], ctx["uid"], nid)


def test_cancel_rev_date(db, ctx):
    nid = notes.receive(db, ctx["book"], ctx["uid"], recv_form(ctx))
    close_id = notes.collect(db, ctx["book"], ctx["uid"], nid, "2026-11-01", ctx["bank"])
    notes.cancel(db, ctx["book"], ctx["uid"], nid, "2026-11-05")
    rev_doc = db.execute("SELECT slip_date FROM erp_docs WHERE source_type='reverse' AND source_id=?",
                         (close_id,)).fetchone()
    assert rev_doc["slip_date"] == "2026-11-05"


def test_closed_period_blocks_collect(db, ctx):
    nid = notes.receive(db, ctx["book"], ctx["uid"], recv_form(ctx))
    db.execute("INSERT INTO fi_closings (company_id, year, month, status, closed_by) VALUES (?,2026,11,'closed',?)",
              (ctx["book"], ctx["uid"]))
    with pytest.raises(ValueError, match="마감"):
        notes.collect(db, ctx["book"], ctx["uid"], nid, "2026-11-01", ctx["bank"])


def test_wrong_state_rejected(db, ctx):
    nid = notes.receive(db, ctx["book"], ctx["uid"], recv_form(ctx))
    notes.collect(db, ctx["book"], ctx["uid"], nid, "2026-11-01", ctx["bank"])
    with pytest.raises(ValueError, match="보유 중"):
        notes.collect(db, ctx["book"], ctx["uid"], nid, "2026-11-02", ctx["bank"])


def test_tenant_isolation(db, ctx):
    nid = notes.receive(db, ctx["book"], ctx["uid"], recv_form(ctx))
    with pytest.raises(LookupError):
        notes.collect(db, ctx["b_book"], ctx["b_uid"], nid, "2026-11-01", ctx["bank"])


def test_slip_source_type_is_note(db, ctx):
    nid = notes.receive(db, ctx["book"], ctx["uid"], recv_form(ctx))
    n = db.execute("SELECT issue_doc_id FROM notes WHERE id=?", (nid,)).fetchone()
    assert db.execute("SELECT source_type FROM erp_docs WHERE id=?", (n["issue_doc_id"],)).fetchone()[0] == "note"


def test_aging_111(db, ctx):
    notes.receive(db, ctx["book"], ctx["uid"], recv_form(ctx))
    items = credit.open_items(db, ctx["book"], "111", ctx["pid"]).get(ctx["pid"], {"items": []})["items"]
    assert len(items) == 1 and items[0]["remain"] == 100000


def test_credit_limit_111(db, ctx):
    db.execute("UPDATE partners SET credit_limit=150000 WHERE id=?", (ctx["pid"],))
    db.execute("UPDATE client_companies SET credit_limit_mode='warn' WHERE id=?", (ctx["book"],))
    db.commit()
    sale(db, ctx, "2026-10-01", 100000)
    notes.receive(db, ctx["book"], ctx["uid"], recv_form(ctx))
    r = credit.check(db, ctx["book"], ctx["pid"], 60000, "2026-10-10")
    assert r is not None and "초과금액: 10,000원" in r["msg"]

from tests.conftest import csrf


def _setup(db, seed, key="a"):
    cid = seed[key]["company"]
    s1 = db.execute("INSERT INTO partners (code, name, partner_type, company_id) VALUES (?,'일공급','supplier',?)",
                    (f"{key}S1", cid)).lastrowid
    s2 = db.execute("INSERT INTO partners (code, name, partner_type, company_id) VALUES (?,'이공급','supplier',?)",
                    (f"{key}S2", cid)).lastrowid
    i1 = db.execute("INSERT INTO items (item_code, item_name, company_id, partner_id) VALUES (?,'볼트',?,?)",
                    (f"{key}I1", cid, s1)).lastrowid
    i2 = db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES (?,'너트',?)", (f"{key}I2", cid)).lastrowid
    pr = db.execute(
        """INSERT INTO purchase_requisitions (pr_number, requester_id, request_date, status, company_id)
           VALUES (?,?,'2026-10-01','approved',?)""", (f"PR-{key}", seed[key]["mgr"], cid)
    ).lastrowid
    db.execute("INSERT INTO pr_lines (pr_id, line_no, item_id, item_name, quantity) VALUES (?,1,?,'볼트',10)", (pr, i1))
    db.execute("INSERT INTO pr_lines (pr_id, line_no, item_id, item_name, quantity) VALUES (?,2,?,'너트',5)", (pr, i2))
    db.commit()
    return {"s1": s1, "s2": s2, "i1": i1, "i2": i2, "pr": pr}


def _create(c, d):
    tok = csrf(c, f"/rfqs/new?pr_id={d['pr']}")
    return c.post("/rfqs", data={"csrf_token": tok, "pr_id": str(d["pr"]), "rfq_date": "2026-10-02",
                                 "partner_id": [str(d["s1"]), str(d["s2"])]}, follow_redirects=False)


def _quote(c, db, rfq, partner_id, prices, lead="3"):
    vid = db.execute("SELECT id FROM rfq_vendors WHERE rfq_id=? AND partner_id=?", (rfq, partner_id)).fetchone()[0]
    lines = [r[0] for r in db.execute("SELECT id FROM rfq_lines WHERE rfq_id=? ORDER BY line_no", (rfq,))]
    data = {"csrf_token": csrf(c, f"/rfqs/{rfq}"), "lead_days": lead}
    data.update({f"price_{l}": str(p) for l, p in zip(lines, prices)})
    return vid, c.post(f"/rfqs/{rfq}/quotes/{vid}", data=data, follow_redirects=False)


def test_rfq_award_to_po(db, seed, login):
    d = _setup(db, seed)
    c = login("a_mgr")
    assert "checked" in c.get(f"/rfqs/new?pr_id={d['pr']}").text
    r = _create(c, d)
    assert r.status_code == 303
    rfq = int(r.headers["location"].rsplit("/", 1)[1])
    assert db.execute("SELECT status FROM purchase_requisitions WHERE id=?", (d["pr"],)).fetchone()[0] == "rfq"

    _quote(c, db, rfq, d["s1"], [100, 200])
    v2, r = _quote(c, db, rfq, d["s2"], [90, 250], lead="5")
    assert r.status_code == 303
    html = c.get(f"/rfqs/{rfq}").text
    assert "2,000" in html and "2,150" in html

    tok = csrf(c, f"/rfqs/{rfq}")
    award = {"csrf_token": tok, "vendor_id": str(v2), "line_role": "결재", "line_user": str(seed["a"]["wk"])}
    r = c.post(f"/rfqs/{rfq}/award", data=award, follow_redirects=False)
    assert r.status_code == 400 and "사유" in r.json()["error"]
    r = c.post(f"/rfqs/{rfq}/award", data={**award, "reason": "납기 우수"}, follow_redirects=False)
    assert r.status_code == 303
    doc = db.execute("SELECT doc_id FROM rfqs WHERE id=?", (rfq,)).fetchone()[0]
    assert db.execute("SELECT source_type FROM erp_docs WHERE id=?", (doc,)).fetchone()[0] == "rfq"

    assert c.post(f"/rfqs/{rfq}/po", data={"csrf_token": tok}, follow_redirects=False).status_code == 400
    _, r = _quote(c, db, rfq, d["s1"], [1, 1])
    assert r.status_code == 400

    w = login("a_wk")
    r = w.post(f"/api/erp_docs/{doc}/approve", data={"csrf_token": csrf(w, f"/erp_doc/{doc}")})
    assert r.json()["new_status"] == "done"

    r = c.post(f"/rfqs/{rfq}/po", data={"csrf_token": tok}, follow_redirects=False)
    assert r.status_code == 303
    po = db.execute("SELECT * FROM purchase_orders WHERE id=(SELECT po_id FROM rfqs WHERE id=?)", (rfq,)).fetchone()
    assert (po["partner_id"], po["status"], po["total_amount"], po["company_id"]) == (d["s2"], "confirmed", 2150, seed["a"]["company"])
    assert [tuple(r) for r in db.execute("SELECT item_id, quantity, unit_price FROM po_lines WHERE po_id=? ORDER BY line_no",
                                         (po["id"],))] == [(d["i1"], 10, 90), (d["i2"], 5, 250)]
    assert db.execute("SELECT status FROM purchase_requisitions WHERE id=?", (d["pr"],)).fetchone()[0] == "converted"
    assert c.post(f"/rfqs/{rfq}/po", data={"csrf_token": tok}, follow_redirects=False).status_code == 400


def test_rfq_rejected_award_can_resubmit_or_cancel(db, seed, login):
    d = _setup(db, seed)
    c = login("a_mgr")
    rfq = int(_create(c, d).headers["location"].rsplit("/", 1)[1])
    v1, _ = _quote(c, db, rfq, d["s1"], [100, 200])
    _, _ = _quote(c, db, rfq, d["s2"], [90])
    tok = csrf(c, f"/rfqs/{rfq}")
    award = {"csrf_token": tok, "line_role": "결재", "line_user": str(seed["a"]["wk"])}
    vid2 = db.execute("SELECT id FROM rfq_vendors WHERE partner_id=?", (d["s2"],)).fetchone()[0]
    assert c.post(f"/rfqs/{rfq}/award", data={**award, "vendor_id": str(vid2)}).status_code == 400
    assert c.post(f"/rfqs/{rfq}/award", data={**award, "vendor_id": str(v1)}, follow_redirects=False).status_code == 303
    assert c.post(f"/rfqs/{rfq}/cancel", data={"csrf_token": tok}).status_code == 400

    doc = db.execute("SELECT doc_id FROM rfqs WHERE id=?", (rfq,)).fetchone()[0]
    w = login("a_wk")
    w.post(f"/api/erp_docs/{doc}/reject", data={"csrf_token": csrf(w, f"/erp_doc/{doc}"), "comment": "재검토"})
    assert c.post(f"/rfqs/{rfq}/cancel", data={"csrf_token": tok}, follow_redirects=False).status_code == 303
    assert db.execute("SELECT status FROM purchase_requisitions WHERE id=?", (d["pr"],)).fetchone()[0] == "approved"


def test_rfq_requires_item_and_vendor(db, seed, login):
    d = _setup(db, seed)
    db.execute("INSERT INTO pr_lines (pr_id, line_no, item_name, quantity) VALUES (?,3,'자유입력',1)", (d["pr"],))
    db.commit()
    c = login("a_mgr")
    assert _create(c, d).status_code == 400
    db.execute("DELETE FROM pr_lines WHERE item_id IS NULL")
    db.commit()
    tok = csrf(c, f"/rfqs/new?pr_id={d['pr']}")
    assert c.post("/rfqs", data={"csrf_token": tok, "pr_id": str(d["pr"])}).status_code == 400


def test_rfq_tenant(db, seed, login):
    d = _setup(db, seed)
    db_b = _setup(db, seed, "b")
    a = login("a_mgr")
    rfq = int(_create(a, d).headers["location"].rsplit("/", 1)[1])
    b = login("b_mgr")
    tok = csrf(b, "/rfqs")
    assert d["pr"] and "RFQ-" not in b.get("/rfqs").text
    assert b.get(f"/rfqs/{rfq}", follow_redirects=False).status_code == 303
    assert b.get(f"/rfqs/new?pr_id={d['pr']}", follow_redirects=False).status_code == 303
    vid = db.execute("SELECT id FROM rfq_vendors WHERE rfq_id=? LIMIT 1", (rfq,)).fetchone()[0]
    assert b.post(f"/rfqs/{rfq}/quotes/{vid}", data={"csrf_token": tok}).status_code == 404
    assert b.post(f"/rfqs/{rfq}/cancel", data={"csrf_token": tok}).status_code == 404
    r = b.post("/rfqs", data={"csrf_token": tok, "pr_id": str(db_b["pr"]), "partner_id": [str(d["s1"])]})
    assert r.status_code == 400
    r = b.post("/rfqs", data={"csrf_token": tok, "pr_id": str(d["pr"]), "partner_id": [str(db_b["s1"])]})
    assert r.status_code == 400

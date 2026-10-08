import json

IFRAME = {"sec-fetch-dest": "iframe"}


def _slip(db, seed):
    a = seed["a"]
    doc = db.execute(
        """INSERT INTO erp_docs (user_id, doc_type, status, slip_date, slip_no, doc_number, company_id, title)
           VALUES (?,'expense','done','2026-09-01','S-1','S-1',?,'매출')""",
        (a["mgr"], a["company"]),
    ).lastrowid
    db.execute("""INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, summary)
                  VALUES (?,1,'외상매출금','110',10000,0,'매출')""", (doc,))
    db.execute("""INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, summary)
                  VALUES (?,2,'매출','401',0,10000,'매출')""", (doc,))
    db.commit()
    return doc


def test_workspace_page(login):
    r = login("a_mgr").get("/workspace")
    assert r.status_code == 200
    assert 'id="mdi"' in r.text
    assert 'data-mdi="on"' in r.text
    assert r.headers["x-frame-options"] == "SAMEORIGIN"


def test_workspace_needs_login(raw_client):
    r = raw_client.get("/workspace", follow_redirects=False)
    assert r.status_code in (302, 303, 307)


def test_embed_drops_widget_and_voice(login):
    c = login("a_mgr")
    full = c.get("/slip_list").text
    framed = c.get("/slip_list", headers=IFRAME).text
    assert 'id="a11yWidget"' in full and "voice.js" in full
    assert 'id="a11yWidget"' not in framed
    assert "voice.js" not in framed
    assert "mdi.js" in framed


def test_mdi_off_for_easy_mode(db, seed, login):
    db.execute("UPDATE users SET accessibility_settings=? WHERE id=?",
               (json.dumps({"easy_mode": True}), seed["a"]["mgr"]))
    db.commit()
    assert 'data-mdi="never"' in login("a_mgr").get("/workspace").text


def test_worker_default_off(login):
    assert 'data-mdi="off"' in login("a_wk").get("/").text


def test_ledger_drilldown_links(db, seed, login):
    doc = _slip(db, seed)
    c = login("a_mgr")
    gl = c.get("/ledger/general?account_code=110&date_from=2026-09-01&date_to=2026-09-30").text
    assert f'href="/erp_doc/{doc}" class="text-decoration-none" data-pop="slip"' in gl
    tb = c.get("/ledger/trial-balance?date_from=2026-09-01&date_to=2026-09-30").text
    assert 'href="/ledger/general?account_code=110&date_from=2026-09-01&date_to=2026-09-30"' in tb


def test_slip_change_watch(db, seed, login):
    doc = _slip(db, seed)
    db.execute("UPDATE erp_docs SET slip_type='대체' WHERE id=?", (doc,))
    db.commit()
    c = login("a_mgr")
    for url in ("/slip_list", "/slip_entry", "/ledger/general", "/ledger/trial-balance", "/report/balance-sheet"):
        assert 'data-watch="slip"' in c.get(url).text, url
    assert 'data-watch' not in c.get("/new_slip").text
    assert "formKit.notifyMaster('slip')" in c.get("/new_slip").text
    assert "formKit.notifyMaster('slip')" in c.get(f"/erp_doc/{doc}").text

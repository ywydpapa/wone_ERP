import re


def _eid(db, uid):
    return db.execute("SELECT id FROM employees WHERE user_id=?", (uid,)).fetchone()[0]


def _contract(db, employee_id):
    return db.execute(
        "SELECT * FROM labor_contracts WHERE employee_id=? ORDER BY version DESC LIMIT 1", (employee_id,)
    ).fetchone()


def _create(login, employee_id, **extra):
    data = {
        "employee_id": employee_id,
        "start_date": "2026-01-01",
        "place": "서울 강남구 공유오피스",
        "duty": "데이터 라벨링",
        "base_pay": "2200000",
        **extra,
    }
    return login("a_mgr").post("/client/labor-contracts", data=data, follow_redirects=False)


def _sign_employer(mgr, cid, password="1234"):
    return mgr.post(f"/client/labor-contracts/{cid}/signature", data={"password": password, "agree": "1"}, follow_redirects=False)


def _sign_worker(wk, cid, name, password="1234"):
    return wk.post(f"/contracts/{cid}/signature", data={"password": password, "sign_name": name, "agree": "1"}, follow_redirects=False)


def test_create_send_sign_flow(db, seed, login):
    eid = _eid(db, seed["a"]["wk"])
    assert _create(login, eid).status_code == 303
    c = _contract(db, eid)
    assert c["status"] == "draft" and c["version"] == 1
    cid = c["id"]

    mgr = login("a_mgr")
    r = _sign_employer(mgr, cid)
    assert r.status_code == 303
    c = _contract(db, eid)
    assert c["status"] == "sent"
    assert c["body_html"] and c["body_hash"]
    assert c["employer_signed_at"] and c["employer_signed_by"]
    assert not c["delivered_at"]

    assert db.execute(
        "SELECT 1 FROM notifications WHERE user_id=? AND link=?", (seed["a"]["wk"], f"/contracts/{cid}")
    ).fetchone()

    wk = login("a_wk")
    assert wk.get(f"/contracts/{cid}").status_code == 200
    assert _contract(db, eid)["delivered_at"]

    emp_name = db.execute("SELECT name FROM employees WHERE id=?", (eid,)).fetchone()["name"]
    r = _sign_worker(wk, cid, emp_name)
    assert r.status_code == 303
    c = _contract(db, eid)
    assert c["status"] == "signed"
    assert c["worker_signed_at"] and c["worker_sign_name"] == emp_name


def test_sent_contract_cannot_be_edited(db, seed, login):
    eid = _eid(db, seed["a"]["wk"])
    _create(login, eid)
    cid = _contract(db, eid)["id"]
    mgr = login("a_mgr")
    _sign_employer(mgr, cid)

    assert mgr.get(f"/client/labor-contracts/{cid}/edit").status_code == 400
    assert mgr.post(
        f"/client/labor-contracts/{cid}",
        data={"start_date": "2026-02-01", "place": "x", "duty": "y", "base_pay": "1"},
    ).status_code == 400


def test_revision_creates_new_version_and_keeps_history(db, seed, login):
    eid = _eid(db, seed["a"]["wk"])
    _create(login, eid)
    cid = _contract(db, eid)["id"]
    mgr = login("a_mgr")
    _sign_employer(mgr, cid)
    emp_name = db.execute("SELECT name FROM employees WHERE id=?", (eid,)).fetchone()["name"]
    _sign_worker(login("a_wk"), cid, emp_name)

    r = mgr.post(f"/client/labor-contracts/{cid}/revisions", follow_redirects=False)
    assert r.status_code == 303
    new = _contract(db, eid)
    assert new["version"] == 2
    assert new["prev_id"] == cid
    assert new["status"] == "draft"

    prev_status = db.execute("SELECT status FROM labor_contracts WHERE id=?", (cid,)).fetchone()["status"]
    assert prev_status == "signed"


def test_wrong_password_blocks_employer_signature(db, seed, login):
    eid = _eid(db, seed["a"]["wk"])
    _create(login, eid)
    cid = _contract(db, eid)["id"]
    mgr = login("a_mgr")
    r = _sign_employer(mgr, cid, password="wrong")
    assert r.status_code == 303
    assert "error=wrong_password" in r.headers["location"]
    assert _contract(db, eid)["status"] == "draft"


def test_wrong_password_blocks_worker_signature(db, seed, login):
    eid = _eid(db, seed["a"]["wk"])
    _create(login, eid)
    cid = _contract(db, eid)["id"]
    mgr = login("a_mgr")
    _sign_employer(mgr, cid)
    emp_name = db.execute("SELECT name FROM employees WHERE id=?", (eid,)).fetchone()["name"]

    r = _sign_worker(login("a_wk"), cid, emp_name, password="wrong")
    assert r.status_code == 303
    assert "error=wrong_password" in r.headers["location"]
    assert _contract(db, eid)["status"] == "sent"


def test_name_mismatch_blocks_worker_signature(db, seed, login):
    eid = _eid(db, seed["a"]["wk"])
    _create(login, eid)
    cid = _contract(db, eid)["id"]
    mgr = login("a_mgr")
    _sign_employer(mgr, cid)

    r = _sign_worker(login("a_wk"), cid, "다른이름")
    assert r.status_code == 303
    assert "error=name_mismatch" in r.headers["location"]
    assert _contract(db, eid)["status"] == "sent"


def test_hash_mismatch_detected_on_tamper(db, seed, login):
    eid = _eid(db, seed["a"]["wk"])
    _create(login, eid)
    cid = _contract(db, eid)["id"]
    mgr = login("a_mgr")
    _sign_employer(mgr, cid)

    db.execute("UPDATE labor_contracts SET body_html = body_html || '<b>tampered</b>' WHERE id=?", (cid,))
    db.commit()

    html = mgr.get(f"/client/labor-contracts/{cid}").text
    assert "원본과 일치하지 않습니다" in html

    emp_name = db.execute("SELECT name FROM employees WHERE id=?", (eid,)).fetchone()["name"]
    r = _sign_worker(login("a_wk"), cid, emp_name)
    assert "error=tampered" in r.headers["location"]
    assert _contract(db, eid)["status"] == "sent"


def test_other_company_manager_gets_404(db, seed, login):
    eid = _eid(db, seed["a"]["wk"])
    _create(login, eid)
    cid = _contract(db, eid)["id"]
    login("a_mgr").post(f"/client/labor-contracts/{cid}/signature", data={"password": "1234", "agree": "1"})

    assert login("b_mgr").get(f"/client/labor-contracts/{cid}").status_code == 404
    assert login("b_mgr").post(f"/client/labor-contracts/{cid}/signature", data={"password": "1234", "agree": "1"}).status_code == 404


def test_other_worker_gets_404(db, seed, login):
    eid = _eid(db, seed["a"]["wk"])
    _create(login, eid)
    cid = _contract(db, eid)["id"]
    login("a_mgr").post(f"/client/labor-contracts/{cid}/signature", data={"password": "1234", "agree": "1"})

    assert login("b_wk").get(f"/contracts/{cid}").status_code == 404
    assert login("b_wk").post(f"/contracts/{cid}/signature", data={"password": "1234", "sign_name": "x", "agree": "1"}).status_code == 404


def test_csrf_required_for_create(raw_client, seed, db):
    def _login_raw(client, username):
        html = client.get("/login").text
        tok = re.search(r"[a-f0-9]{64}", html).group(0)
        return client.post("/login_check", data={"username": username, "password": "1234", "csrf_token": tok}, follow_redirects=False)

    eid = _eid(db, seed["a"]["wk"])
    _login_raw(raw_client, "a_mgr")

    r = raw_client.post(
        "/client/labor-contracts",
        data={"employee_id": eid, "start_date": "2026-01-01", "place": "x", "duty": "y", "base_pay": "1"},
    )
    assert r.status_code == 403
    assert not _contract(db, eid)

    tok = re.search(r"[a-f0-9]{64}", raw_client.get("/client/labor-contracts").text).group(0)
    r2 = raw_client.post(
        "/client/labor-contracts",
        data={"employee_id": eid, "start_date": "2026-01-01", "place": "x", "duty": "y", "base_pay": "1",
              "csrf_token": tok},
        follow_redirects=False,
    )
    assert r2.status_code == 303
    assert _contract(db, eid)

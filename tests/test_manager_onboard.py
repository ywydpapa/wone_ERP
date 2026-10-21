import re

from fastapi.testclient import TestClient

from core.auth import is_legacy, verify_pw
from main import app


def _create_manager(staff, cid, username, name="새담당자", client_role="all"):
    return staff.post(
        f"/platform/companies/{cid}/managers",
        data={"name": name, "username": username, "phone": "", "client_role": client_role},
    )


def _extract_temp_pw(html):
    return re.search(r"<code>([^<]+)</code>", html).group(1)


def test_staff_creates_manager_account(db, seed, login):
    staff = login("t_staff")
    cid = seed["a"]["company"]
    r = _create_manager(staff, cid, "new_mgr1")
    assert r.status_code == 200
    temp_pw = _extract_temp_pw(r.text)

    user = db.execute("SELECT * FROM users WHERE username='new_mgr1'").fetchone()
    assert user is not None
    assert user["must_change_password"] == 1
    assert not is_legacy(user["password"])
    assert verify_pw(temp_pw, user["password"])

    cu = db.execute("SELECT * FROM client_users WHERE user_id=?", (user["id"],)).fetchone()
    assert cu["company_id"] == cid
    assert cu["client_role"] == "all"


def test_non_staff_cannot_create_manager(seed, login):
    cid = seed["a"]["company"]
    mgr = login("a_mgr")
    r = mgr.post(
        f"/platform/companies/{cid}/managers",
        data={"name": "x", "username": "hack1", "phone": "", "client_role": "all"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"

    wk = login("a_wk")
    r2 = wk.post(
        f"/platform/companies/{cid}/managers",
        data={"name": "x", "username": "hack2", "phone": "", "client_role": "all"},
        follow_redirects=False,
    )
    assert r2.status_code == 303
    assert r2.headers["location"] == "/"


def test_duplicate_username_rejected(db, seed, login):
    staff = login("t_staff")
    cid = seed["a"]["company"]
    before = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    r = _create_manager(staff, cid, "a_mgr")
    assert "error=dup_username" in str(r.url)
    after = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    assert before == after


def test_new_manager_must_change_password_before_other_pages(db, seed, login):
    staff = login("t_staff")
    cid = seed["a"]["company"]
    r = _create_manager(staff, cid, "new_mgr2")
    temp_pw = _extract_temp_pw(r.text)

    c = TestClient(app)
    c.get("/login")
    c.post("/login_check", data={"username": "new_mgr2", "password": temp_pw})

    blocked = c.get("/client/requests", follow_redirects=False)
    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/mypage/profile?pw_required=1"

    changed = c.post(
        "/mypage/profile/password",
        data={"current_password": temp_pw, "new_password": "newpass123", "confirm_password": "newpass123"},
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert changed.headers["location"] == "/mypage/profile?pw_changed=1"

    ok = c.get("/client/requests")
    assert ok.status_code == 200

    user = db.execute("SELECT must_change_password FROM users WHERE username='new_mgr2'").fetchone()
    assert user["must_change_password"] == 0


def test_reissue_wrong_company_404(seed, login):
    staff = login("t_staff")
    b_cid = seed["b"]["company"]
    r = staff.post(f"/platform/companies/{b_cid}/managers/{seed['a']['mgr']}/password")
    assert r.status_code == 404


def test_reissue_resets_password(db, seed, login):
    staff = login("t_staff")
    cid = seed["a"]["company"]
    r = _create_manager(staff, cid, "new_mgr4")
    temp_pw1 = _extract_temp_pw(r.text)
    uid = db.execute("SELECT id FROM users WHERE username='new_mgr4'").fetchone()["id"]

    r2 = staff.post(f"/platform/companies/{cid}/managers/{uid}/password")
    assert r2.status_code == 200
    temp_pw2 = _extract_temp_pw(r2.text)
    assert temp_pw2 != temp_pw1

    user = db.execute("SELECT must_change_password FROM users WHERE id=?", (uid,)).fetchone()
    assert user["must_change_password"] == 1

    c = TestClient(app)
    c.get("/login")
    fail = c.post("/login_check", data={"username": "new_mgr4", "password": temp_pw1}, follow_redirects=False)
    assert fail.headers["location"] != "/"

    c2 = TestClient(app)
    c2.get("/login")
    ok = c2.post("/login_check", data={"username": "new_mgr4", "password": temp_pw2}, follow_redirects=False)
    assert ok.headers["location"] == "/"


def test_audit_logs_recorded(db, seed, login):
    staff = login("t_staff")
    cid = seed["a"]["company"]
    _create_manager(staff, cid, "new_mgr5")
    uid = db.execute("SELECT id FROM users WHERE username='new_mgr5'").fetchone()["id"]
    staff.post(f"/platform/companies/{cid}/managers/{uid}/password")

    actions = [r["action"] for r in db.execute(
        "SELECT action FROM audit_logs WHERE target_id=? ORDER BY id", (uid,)
    ).fetchall()]
    assert "manager_create" in actions
    assert "manager_pw_reset" in actions

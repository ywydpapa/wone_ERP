import re
from datetime import timedelta

import core.rate_limit as rate_limit
from tests.conftest import csrf
from core.perms import group_of_path
from core.tz import now_kst


def _set_perm(db, uid, group, level):
    db.execute(
        "INSERT INTO user_perms (user_id, group_key, level) VALUES (?,?,?) "
        "ON CONFLICT(user_id, group_key) DO UPDATE SET level=excluded.level",
        (uid, group, level),
    )
    db.commit()


def test_prefix_boundary_check():
    assert group_of_path("/fi/closing") == "fi"
    assert group_of_path("/fiscal") is None


def test_longest_prefix_wins():
    assert group_of_path("/partners") == "mm"
    assert group_of_path("/partners/contacts") == "sales"


def test_doc_path_no_group():
    assert group_of_path("/erp_doc/1") is None
    assert group_of_path("/api/erp_docs/1/approve") is None


def test_group_of_path_fa():
    assert group_of_path("/erp_fa") == "fi"


def test_none_level_blocks_module_dashboard(db, seed, login):
    _set_perm(db, seed["a"]["wk"], "hr", "none")
    assert login("a_wk").get("/erp_hr").status_code == 403


def test_client_ip_ignores_xff(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUST_PROXY", False)
    req = type("R", (), {
        "headers": {"x-forwarded-for": "1.2.3.4"},
        "client": type("C", (), {"host": "127.0.0.1"})(),
    })()
    assert rate_limit.get_client_ip(req) == "127.0.0.1"


def test_no_row_keeps_default_edit(login):
    c = login("a_mgr")
    assert c.get("/partners").status_code == 200
    r = c.post("/partners/save", data={"csrf_token": csrf(c), "name": "새거래처"})
    assert r.status_code != 403


def test_view_level_blocks_write(db, seed, login):
    _set_perm(db, seed["a"]["mgr"], "mm", "view")
    c = login("a_mgr")
    assert c.get("/partners").status_code == 200
    r = c.post("/partners/save", data={"csrf_token": csrf(c), "name": "새거래처2"})
    assert r.status_code == 403


def test_none_level_blocks_read(db, seed, login):
    _set_perm(db, seed["a"]["mgr"], "mm", "none")
    c = login("a_mgr")
    assert c.get("/partners").status_code == 403
    t = c.get("/").text
    assert 'sidebar-parent menu-off" data-menu="mm"' in t


def test_cross_company_patch_blocked(seed, login):
    c = login("a_mgr")
    r = c.patch(f"/users/{seed['b']['mgr']}/lock", data={"csrf_token": csrf(c)})
    assert r.status_code == 404


def test_worker_forbidden_from_user_list(login):
    c = login("a_wk")
    assert c.get("/users").status_code == 403


def test_user_list_shows_last_login(login):
    c = login("a_mgr")
    r = c.get("/users")
    assert r.status_code == 200
    assert "a_mgr" in r.text


def test_unlock_allows_login_again(db, seed, login, raw_client):
    future = (now_kst() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE users SET locked_until=? WHERE id=?", (future, seed["a"]["wk"]))
    db.commit()

    staff = login("t_staff")
    r = staff.patch(f"/users/{seed['a']['wk']}/lock", data={"csrf_token": csrf(staff)})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert not db.execute("SELECT locked_until FROM users WHERE id=?", (seed["a"]["wk"],)).fetchone()["locked_until"]
    assert db.execute("SELECT 1 FROM audit_logs WHERE action='user_unlock'").fetchone()

    html = raw_client.get("/login").text
    tok = re.search(r"[a-f0-9]{64}", html).group(0)
    r2 = raw_client.post(
        "/login_check", data={"username": "a_wk", "password": "1234", "csrf_token": tok},
        follow_redirects=False,
    )
    assert r2.headers["location"] == "/"


def test_staff_changes_client_role(db, seed, login):
    staff = login("t_staff")
    r = staff.patch(f"/users/{seed['a']['mgr']}/role", data={"csrf_token": csrf(staff), "client_role": "hr"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    row = db.execute("SELECT client_role FROM client_users WHERE user_id=?", (seed["a"]["mgr"],)).fetchone()
    assert row["client_role"] == "hr"
    log = db.execute("SELECT detail FROM audit_logs WHERE action='role_change'").fetchone()
    assert log and '"hr"' in log["detail"]


def test_staff_sets_client_role_ops(db, seed, login):
    staff = login("t_staff")
    r = staff.patch(f"/users/{seed['a']['mgr']}/role", data={"csrf_token": csrf(staff), "client_role": "ops"})
    assert r.status_code == 200
    row = db.execute("SELECT client_role FROM client_users WHERE user_id=?", (seed["a"]["mgr"],)).fetchone()
    assert row["client_role"] == "ops"


def test_cannot_lower_own_admin_perm(seed, login):
    staff = login("t_staff")
    r = staff.patch(f"/users/{seed['staff']}/perms", data={"csrf_token": csrf(staff), "perm_admin": "view"})
    assert r.status_code == 400
    assert "본인의 관리 권한" in r.json()["error"]


def test_perm_update_writes_audit_detail(db, seed, login):
    staff = login("t_staff")
    r = staff.patch(f"/users/{seed['a']['mgr']}/perms", data={"csrf_token": csrf(staff), "perm_mm": "none"})
    assert r.status_code == 200
    row = db.execute("SELECT level FROM user_perms WHERE user_id=? AND group_key='mm'", (seed["a"]["mgr"],)).fetchone()
    assert row["level"] == "none"
    log = db.execute("SELECT detail FROM audit_logs WHERE action='perm_update'").fetchone()
    assert log and '"edit"' in log["detail"] and '"none"' in log["detail"]

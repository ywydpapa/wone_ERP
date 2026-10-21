from datetime import timedelta

from tests.conftest import csrf
from core.tz import now_kst


def test_lock_mid_session_kicks_out(db, seed, login):
    c = login("a_wk")
    assert c.get("/mypage/leave", follow_redirects=False).status_code == 200

    future = (now_kst() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE users SET locked_until=? WHERE id=?", (future, seed["a"]["wk"]))
    db.commit()

    r = c.get("/mypage/leave", follow_redirects=False)
    assert "error=locked" in r.headers["location"]


def test_force_logout_cuts_live_session(db, seed, login):
    c = login("a_wk")
    assert c.get("/mypage/leave", follow_redirects=False).status_code == 200

    staff = login("t_staff")
    r = staff.patch(f"/users/{seed['a']['wk']}/force-logout", data={"csrf_token": csrf(staff)})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert db.execute("SELECT 1 FROM audit_logs WHERE action='user_force_logout'").fetchone()

    r = c.get("/mypage/leave", follow_redirects=False)
    assert "error=forced" in r.headers["location"]


def test_force_logout_out_of_scope_404(seed, login):
    a_mgr = login("a_mgr")
    r = a_mgr.patch(f"/users/{seed['b']['wk']}/force-logout", data={"csrf_token": csrf(a_mgr)})
    assert r.status_code == 404


def test_client_role_downgrade_applies_without_relogin(db, seed, login):
    c = login("a_mgr")
    assert c.get("/payroll").status_code == 200

    db.execute("UPDATE client_users SET client_role='ops' WHERE user_id=?", (seed["a"]["mgr"],))
    db.commit()

    r = c.get("/payroll", follow_redirects=False)
    assert r.status_code in (302, 303)

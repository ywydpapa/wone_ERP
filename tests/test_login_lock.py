import itertools
import re
from datetime import timedelta

import pytest

import core.rate_limit as rate_limit
from core.rate_limit import _store
from core.tz import now_kst
import routers.auth as auth_mod


@pytest.fixture(autouse=True)
def _trust_proxy(monkeypatch):
    # 시도마다 XFF를 바꿔 IP 제한을 피하므로 프록시 신뢰 전제
    monkeypatch.setattr(rate_limit, "TRUST_PROXY", True)


def _csrf(client):
    html = client.get("/login").text
    return re.search(r"[a-f0-9]{64}", html).group(0)


def _attempt(client, tok, username, password, ip):
    return client.post(
        "/login_check",
        data={"username": username, "password": password, "csrf_token": tok},
        headers={"X-Forwarded-For": ip},
        follow_redirects=False,
    )


def test_lockout_after_5_fails(raw_client, seed, db):
    _store.clear()
    tok = _csrf(raw_client)
    ips = itertools.count(1)
    for _ in range(4):
        r = _attempt(raw_client, tok, "a_wk", "wrong", f"10.0.1.{next(ips)}")
        assert r.headers["location"] == "/login?error=1"

    r = _attempt(raw_client, tok, "a_wk", "wrong", f"10.0.1.{next(ips)}")
    assert r.headers["location"] == "/login?error=locked"

    row = db.execute("SELECT locked_until FROM users WHERE username='a_wk'").fetchone()
    assert row["locked_until"]

    # 잠긴 동안은 비번이 맞아도 실패 처리
    r = _attempt(raw_client, tok, "a_wk", "1234", f"10.0.1.{next(ips)}")
    assert r.headers["location"] == "/login?error=locked"


def test_lock_expires_after_30_min(raw_client, seed, db, monkeypatch):
    _store.clear()
    tok = _csrf(raw_client)
    ips = itertools.count(1)
    for _ in range(5):
        _attempt(raw_client, tok, "a_wk", "wrong", f"10.0.2.{next(ips)}")

    future = now_kst() + timedelta(minutes=31)
    monkeypatch.setattr(auth_mod, "now_kst", lambda: future)

    r = _attempt(raw_client, tok, "a_wk", "1234", f"10.0.2.{next(ips)}")
    assert r.headers["location"] == "/"

    last = db.execute(
        "SELECT ok FROM login_attempts WHERE username='a_wk' ORDER BY at DESC LIMIT 1"
    ).fetchone()
    assert last["ok"] == 1


def test_four_fails_then_success_resets_count(raw_client, seed, db):
    _store.clear()
    tok = _csrf(raw_client)
    ips = itertools.count(1)
    for _ in range(4):
        r = _attempt(raw_client, tok, "a_wk", "wrong", f"10.0.3.{next(ips)}")
        assert r.headers["location"] == "/login?error=1"

    r = _attempt(raw_client, tok, "a_wk", "1234", f"10.0.3.{next(ips)}")
    assert r.headers["location"] == "/"

    row = db.execute("SELECT locked_until FROM users WHERE username='a_wk'").fetchone()
    assert not row["locked_until"]


def test_nonexistent_account_locks_without_exposing(raw_client, seed, db):
    _store.clear()
    tok = _csrf(raw_client)
    ips = itertools.count(1)
    for _ in range(4):
        r = _attempt(raw_client, tok, "ghost", "wrong", f"10.0.4.{next(ips)}")
        assert r.headers["location"] == "/login?error=1"

    r = _attempt(raw_client, tok, "ghost", "wrong", f"10.0.4.{next(ips)}")
    assert r.headers["location"] == "/login?error=locked"
    assert not db.execute("SELECT 1 FROM users WHERE username='ghost'").fetchone()


def test_audit_log_actions(raw_client, seed, db):
    _store.clear()
    tok = _csrf(raw_client)
    ips = itertools.count(1)

    _attempt(raw_client, tok, "a_wk", "wrong", f"10.0.5.{next(ips)}")
    assert db.execute("SELECT 1 FROM audit_logs WHERE action='login_fail'").fetchone()

    for _ in range(4):
        _attempt(raw_client, tok, "a_wk", "wrong", f"10.0.5.{next(ips)}")
    assert db.execute("SELECT 1 FROM audit_logs WHERE action='login_lock'").fetchone()

    _store.clear()
    tok2 = _csrf(raw_client)
    r = _attempt(raw_client, tok2, "a_mgr", "1234", f"10.0.5.{next(ips)}")
    assert r.headers["location"] == "/"
    assert db.execute("SELECT 1 FROM audit_logs WHERE action='login'").fetchone()


def test_login_history_shows_own_only(raw_client, seed, db):
    _store.clear()
    tok = _csrf(raw_client)
    ips = itertools.count(1)
    _attempt(raw_client, tok, "b_mgr", "wrong", f"10.0.6.{next(ips)}")
    r = _attempt(raw_client, tok, "a_wk", "1234", f"10.0.6.{next(ips)}")
    assert r.headers["location"] == "/"

    page = raw_client.get("/mypage/login-history")
    assert page.status_code == 200
    assert "b_mgr" not in page.text

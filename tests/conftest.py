import hashlib
import os
import re
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrate import run_migrations
from core.csrf import verify_csrf


def _connect(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _user(conn, username, role, name):
    pw = hashlib.sha256(b"1234").hexdigest()
    cur = conn.execute(
        "INSERT INTO users (username, password, name, role) VALUES (?,?,?,?)",
        (username, pw, name, role),
    )
    return cur.lastrowid


def seed_companies(conn):
    ids = {}
    for key, name in (("a", "가테스트"), ("b", "나테스트")):
        cid = conn.execute("INSERT INTO client_companies (name) VALUES (?)", (name,)).lastrowid
        mgr = _user(conn, f"{key}_mgr", "client", f"{name}담당")
        conn.execute("INSERT INTO client_users (user_id, company_id) VALUES (?,?)", (mgr, cid))
        wk = _user(conn, f"{key}_wk", "worker", f"{name}근로자")
        conn.execute("INSERT INTO employees (user_id, name, company_id) VALUES (?,?,?)", (wk, f"{name}근로자", cid))
        ids[key] = {"company": cid, "mgr": mgr, "wk": wk}
    ids["staff"] = _user(conn, "t_staff", "platform_staff", "스태프")
    conn.commit()
    return ids


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "t.db")
    run_migrations(path)
    return path


@pytest.fixture
def db(db_path):
    conn = _connect(db_path)
    yield conn
    conn.close()


@pytest.fixture
def seed(db):
    from core.books import seed_accounts
    ids = seed_companies(db)
    seed_accounts(db, ids["a"]["company"])
    seed_accounts(db, ids["b"]["company"])
    db.commit()
    return ids


@pytest.fixture
def login(db_path, seed, monkeypatch):
    import core.db
    monkeypatch.setattr(core.db, "DB_PATH", db_path)
    from fastapi.testclient import TestClient
    from main import app

    # 기존 테스트는 CSRF 토큰 없이 그냥 post. 기본적으로 우회 처리
    app.dependency_overrides[verify_csrf] = lambda: None

    def _login(username):
        c = TestClient(app)
        html = c.get("/login").text
        tok = re.search(r"[a-f0-9]{64}", html).group(0)
        c.post("/login_check", data={"username": username, "password": "1234", "csrf_token": tok})
        return c

    yield _login
    app.dependency_overrides.pop(verify_csrf, None)


def csrf(client, path="/new_slip"):
    return re.search(r"[a-f0-9]{64}", client.get(path).text).group(0)


@pytest.fixture
def raw_client(db_path, seed, monkeypatch):
    # CSRF를 우회하지 않는 순수 클라이언트. CSRF/idle 타임아웃 테스트 전용
    import core.db
    monkeypatch.setattr(core.db, "DB_PATH", db_path)
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)

import os
import sqlite3
import time
from datetime import datetime

from tests.conftest import csrf
from core import backup
from core.tz import KST
import routers.settings as settings_mod


def _mk_src(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users (name) VALUES ('가')")
    conn.commit()
    conn.close()
    return path


def test_run_creates_db_with_tables(tmp_path):
    src = _mk_src(str(tmp_path / "src.db"))
    dest = tmp_path / "dest"
    path = backup.run(src, dest)
    assert path.startswith(str(dest))
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT name FROM users").fetchone()[0] == "가"
    conn.close()


def test_run_second_call_same_minute_appends_seconds(tmp_path, monkeypatch):
    src = _mk_src(str(tmp_path / "src.db"))
    dest = tmp_path / "dest"
    fixed = datetime(2026, 10, 12, 3, 0, 1, tzinfo=KST)
    monkeypatch.setattr(backup, "now_kst", lambda: fixed)

    p1 = backup.run(src, dest)
    p2 = backup.run(src, dest)
    assert p1 != p2
    assert p1.endswith("erp-20261012-0300.db")


def test_run_deletes_files_older_than_keep_days(tmp_path):
    src = _mk_src(str(tmp_path / "src.db"))
    dest = tmp_path / "dest"
    dest.mkdir()
    old = dest / "erp-20260101-0300.db"
    old.write_bytes(b"old")
    old_mtime = time.time() - 15 * 86400
    os.utime(old, (old_mtime, old_mtime))

    backup.run(src, dest, keep_days=14)
    assert not old.exists()


def test_files_lists_newest_first(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    a = dest / "erp-20260101-0300.db"
    b = dest / "erp-20260102-0300.db"
    a.write_bytes(b"a")
    b.write_bytes(b"bb")
    now = time.time()
    os.utime(a, (now - 100, now - 100))
    os.utime(b, (now, now))

    rows = backup.files(dest)
    assert [r["name"] for r in rows] == ["erp-20260102-0300.db", "erp-20260101-0300.db"]
    assert rows[0]["size"] == 2
    assert rows[0]["at"]


def test_staff_can_view_backup_list(login, monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "BACKUP_DIR", tmp_path)
    c = login("t_staff")
    r = c.get("/settings/backup")
    assert r.status_code == 200


def test_client_mgr_forbidden(login, monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "BACKUP_DIR", tmp_path)
    c = login("a_mgr")
    r = c.get("/settings/backup")
    assert r.status_code == 403


def test_download_rejects_bad_name(login, monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "BACKUP_DIR", tmp_path)
    (tmp_path / "erp.db").write_bytes(b"x")
    c = login("t_staff")
    r = c.get("/settings/backup/../erp.db")
    assert r.status_code == 404
    r2 = c.get("/settings/backup/not-a-backup.txt")
    assert r2.status_code == 404


def test_post_backup_creates_file_and_audit_log(db, login, monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "BACKUP_DIR", tmp_path)
    c = login("t_staff")
    before = len(list(tmp_path.glob("erp-*.db"))) if tmp_path.exists() else 0
    tok = csrf(c, "/settings/backup")
    r = c.post("/settings/backup", data={"csrf_token": tok}, follow_redirects=False)
    assert r.status_code == 303
    after = len(list(tmp_path.glob("erp-*.db")))
    assert after == before + 1
    assert db.execute("SELECT 1 FROM audit_logs WHERE action='backup'").fetchone()

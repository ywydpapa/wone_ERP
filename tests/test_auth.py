import hashlib
import re

from core.auth import hash_pw, verify_pw, is_legacy


def test_hash_verify_roundtrip():
    hashed = hash_pw("1234")
    assert verify_pw("1234", hashed)


def test_wrong_password_fails():
    hashed = hash_pw("1234")
    assert not verify_pw("5678", hashed)


def test_same_password_different_salt():
    a = hash_pw("1234")
    b = hash_pw("1234")
    assert a != b


def test_legacy_sha256_still_verifies():
    legacy = hashlib.sha256(b"1234").hexdigest()
    assert is_legacy(legacy)
    assert verify_pw("1234", legacy)


def test_legacy_login_upgrades_hash(raw_client, seed, db):
    legacy = hashlib.sha256(b"1234").hexdigest()
    db.execute("UPDATE users SET password=? WHERE username=?", (legacy, "a_wk"))
    db.commit()

    html = raw_client.get("/login").text
    tok = re.search(r"[a-f0-9]{64}", html).group(0)
    r = raw_client.post(
        "/login_check",
        data={"username": "a_wk", "password": "1234", "csrf_token": tok},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"

    row = db.execute("SELECT password FROM users WHERE username=?", ("a_wk",)).fetchone()
    assert not is_legacy(row["password"])
    assert verify_pw("1234", row["password"])

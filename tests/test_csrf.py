import pathlib
import re

from core.deps import IDLE_TIMEOUT

REPO = pathlib.Path(__file__).resolve().parent.parent

def _login_raw(client, username):
    html = client.get("/login").text
    tok = re.search(r"[a-f0-9]{64}", html).group(0)
    return client.post(
        "/login_check",
        data={"username": username, "password": "1234", "csrf_token": tok},
        follow_redirects=False,
    )


def test_login_from_fresh_session(raw_client, seed):
    r = _login_raw(raw_client, "a_wk")
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_post_without_token_is_403(raw_client, seed):
    _login_raw(raw_client, "a_wk")
    r = raw_client.post("/daily-report/quick-memo", data={"title": "메모"})
    assert r.status_code == 403


def test_post_with_session_token_succeeds(raw_client, seed):
    _login_raw(raw_client, "a_wk")
    tok = re.search(r"[a-f0-9]{64}", raw_client.get("/daily-report").text).group(0)
    r = raw_client.post(
        "/daily-report/quick-memo",
        data={"title": "메모", "csrf_token": tok},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_json_post_not_blocked_by_csrf(raw_client, seed):
    _login_raw(raw_client, "a_wk")
    r = raw_client.post("/api/accessibility", json={"font_size": 150})
    assert r.status_code == 200


def test_idle_timeout_redirects_to_login(raw_client, seed, monkeypatch):
    _login_raw(raw_client, "a_wk")
    raw_client.get("/daily-report")  # last_seen 기록
    import core.deps as deps
    now = deps.time.time()
    monkeypatch.setattr(deps.time, "time", lambda: now + IDLE_TIMEOUT + 1)
    r = raw_client.get("/daily-report", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login?error=timeout"


def test_all_post_forms_have_csrf_token():
    form_open_re = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
    method_post_re = re.compile(r"method\s*=\s*[\"']?post", re.IGNORECASE)
    missing = []

    for f in sorted(REPO.glob("templates/**/*.html")):
        text = f.read_text()
        rel = str(f.relative_to(REPO))
        for m in form_open_re.finditer(text):
            if not method_post_re.search(m.group(0)):
                continue
            close = text.find("</form>", m.end())
            body = text[m.end():close if close != -1 else len(text)]
            if "csrf_input" in body or "csrf_token" in body:
                continue
            line_no = text[:m.start()].count("\n") + 1
            missing.append(f"{rel}:{line_no}")

    assert not missing, f"csrf_input 없는 post form: {missing}"

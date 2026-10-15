import json


def saved(db, user_id):
    row = db.execute("SELECT accessibility_settings FROM users WHERE id=?", (user_id,)).fetchone()
    return json.loads(row["accessibility_settings"])


def test_save_a11y_whitelist(db, seed, login):
    c = login("a_mgr")
    r = c.post("/api/accessibility", json={"font_size": 150, "high_contrast": True, "tts_voice": "X1", "theme": "dark"})
    assert r.json()["ok"]
    s = saved(db, seed["a"]["mgr"])
    assert s["font_size"] == 150
    assert s["high_contrast"] is True
    assert s["tts_voice"] == "F1"
    assert "theme" not in s


def test_sr_mode_saves(db, seed, login):
    c = login("a_mgr")
    r = c.post("/api/accessibility", json={"sr_mode": True})
    assert r.json()["ok"]
    s = saved(db, seed["a"]["mgr"])
    assert s["sr_mode"] is True


def test_sr_mode_default_false(db, seed, login):
    c = login("a_mgr")
    c.post("/api/accessibility", json={"font_size": 150})
    s = saved(db, seed["a"]["mgr"])
    assert s["sr_mode"] is False


def test_a11y_applied_to_page(login):
    c = login("a_mgr")
    c.post("/api/accessibility", json={"font_size": 200, "high_contrast": True})
    html = c.get("/workspace").text
    assert 'class="font-xl"' in html
    assert "theme-high-contrast" in html
    assert 'id="a11yWidget"' in html
    assert 'id="a11yWSrMode"' in html


def test_save_a11y_unauthed(raw_client):
    # CSRF 검증이 로그인 체크보다 앞서 동작하여 403으로 막힘
    r = raw_client.post("/api/accessibility", json={"font_size": 150}, follow_redirects=False)
    assert r.status_code == 403

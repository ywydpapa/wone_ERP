from tests.conftest import csrf


def test_generate_publish_and_client_view(db, seed, login):
    a = seed["a"]["company"]
    db.execute("UPDATE employees SET employment_insurance=1 WHERE company_id=?", (a,))
    db.commit()
    st = login("t_staff")
    r = st.post("/platform/monthly-report/generate", data={
        "company_id": str(a), "target_month": "2026-10", "csrf_token": csrf(st, "/platform/monthly-report"),
    }, follow_redirects=False)
    assert r.status_code == 303
    rid = db.execute("SELECT id FROM monthly_reports WHERE company_id=? AND year=2026 AND month=10", (a,)).fetchone()["id"]
    assert st.get(f"/platform/monthly-report/{rid}").status_code == 200
    assert st.get(f"/platform/monthly-report/{rid}/pdf").headers["content-type"] == "application/pdf"

    ca = login("a_mgr")
    assert ca.get("/client/monthly-report/2026/10", follow_redirects=False).status_code == 303

    st.post(f"/platform/monthly-report/{rid}/publish", data={
        "csrf_token": csrf(st, f"/platform/monthly-report/{rid}"),
    }, follow_redirects=False)
    assert ca.get("/client/monthly-report/2026/10").status_code == 200
    assert ca.get("/client/monthly-report/2026/10/pdf").headers["content-type"] == "application/pdf"
    assert login("b_mgr").get("/client/monthly-report/2026/10", follow_redirects=False).status_code == 303

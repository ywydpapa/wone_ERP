def _set_client_role(db, user_id, role):
    db.execute("UPDATE client_users SET client_role=? WHERE user_id=?", (role, user_id))
    db.commit()


def _sidebar(html):
    # 대시보드 본문에도 동일 링크가 나올 수 있음. 사이드바 영역만 추출함
    start = html.find('<nav class="sidebar-nav"')
    end = html.find('</nav>', start)
    return html[start:end]


def test_staff_sees_hr_domain(db, seed, login):
    html = login("t_staff").get("/").text
    nav = _sidebar(html)
    assert "인사/급여" in nav
    assert 'href="/roster"' in nav
    assert 'href="/payroll/ledger"' in nav
    assert 'href="/leave_approvals"' in nav
    assert 'href="/withholding"' in nav
    assert 'href="/insurance-reports"' in nav
    assert html.count('href="/payroll/ledger"') == 1


def test_client_hr_sees_payroll_leave_not_attendance(db, seed, login):
    _set_client_role(db, seed["a"]["mgr"], "hr")
    nav = _sidebar(login("a_mgr").get("/").text)
    assert "인사/급여" in nav
    assert 'href="/payroll"' in nav
    assert 'href="/pay-items"' in nav
    assert 'href="/client/leave/calendar"' in nav
    assert 'href="/withholding/simple-statement"' in nav
    assert 'href="/client/attendance"' not in nav
    assert 'href="/client/attendance/sheet"' not in nav


def test_client_ops_sees_attendance_not_payroll(db, seed, login):
    _set_client_role(db, seed["b"]["mgr"], "ops")
    nav = _sidebar(login("b_mgr").get("/").text)
    assert "인사/급여" in nav
    assert 'href="/client/attendance"' in nav
    assert 'href="/client/attendance/sheet"' in nav
    assert 'href="/payroll"' not in nav
    assert 'href="/withholding"' not in nav
    assert 'href="/client/leave/calendar"' not in nav


def test_worker_has_no_hr_domain(db, seed, login):
    nav = _sidebar(login("a_wk").get("/").text)
    assert "인사/급여" not in nav

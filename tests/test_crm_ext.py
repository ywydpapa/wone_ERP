import pytest


def _partner(db, cid, code, name, **kw):
    cols = ["code", "name", "company_id", *kw]
    return db.execute(f"INSERT INTO partners ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                      (code, name, cid, *kw.values())).lastrowid


def _contact(db, cid, pid, name):
    return db.execute("INSERT INTO partner_contacts (company_id, partner_id, name) VALUES (?,?,?)",
                      (cid, pid, name)).lastrowid


def _slip(db, cid, uid, day, pid, debit, credit_amt, no):
    doc = db.execute(
        """INSERT INTO erp_docs (user_id, doc_type, status, slip_date, slip_no, doc_number, company_id, title)
           VALUES (?,'expense','done',?,?,?,?,'t')""",
        (uid, day, no, no, cid),
    ).lastrowid
    db.execute(
        """INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner_id)
           VALUES (?,1,'외상매출금','110',?,?,?)""",
        (doc, debit, credit_amt, pid),
    )


@pytest.fixture
def co(db, seed):
    a, b = seed["a"], seed["b"]
    pid = _partner(db, a["company"], "C1", "가고객", partner_type="customer")
    other = _partner(db, b["company"], "X1", "남의고객", partner_type="customer")
    contact = _contact(db, a["company"], pid, "김담당")
    other_contact = _contact(db, b["company"], other, "타사담당")
    db.commit()
    return {"cid": a["company"], "mgr": a["mgr"], "wk": a["wk"], "b_cid": b["company"], "b_mgr": b["mgr"],
            "pid": pid, "other": other, "contact": contact, "other_contact": other_contact}


# 영업활동 담당자

def test_activity_save_own_contact_stored(db, co, login):
    c = login("a_mgr")
    r = c.post("/crm/activities/save", data={"partner_id": str(co["pid"]), "contact_id": str(co["contact"]),
                                             "kind": "call", "act_date": "2026-10-01", "subject": "방문"},
               follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT contact_id FROM crm_activities WHERE subject='방문'").fetchone()[0] == co["contact"]


def test_activity_save_other_partner_contact_dropped(db, co, login):
    c = login("a_mgr")
    pid2 = _partner(db, co["cid"], "C2", "나고객", partner_type="customer")
    other_contact = _contact(db, co["cid"], pid2, "박담당")
    db.commit()
    # 같은 회사 소속이지만 다른 거래처의 담당자는 저장되지 않음
    c.post("/crm/activities/save", data={"partner_id": str(co["pid"]), "contact_id": str(other_contact),
                                         "kind": "call", "act_date": "2026-10-01", "subject": "오류1"})
    assert db.execute("SELECT contact_id FROM crm_activities WHERE subject='오류1'").fetchone()[0] is None


def test_activity_save_other_company_contact_dropped(db, co, login):
    c = login("a_mgr")
    c.post("/crm/activities/save", data={"partner_id": str(co["pid"]), "contact_id": str(co["other_contact"]),
                                         "kind": "call", "act_date": "2026-10-01", "subject": "오류2"})
    assert db.execute("SELECT contact_id FROM crm_activities WHERE subject='오류2'").fetchone()[0] is None


def test_activity_list_filter_by_contact(db, co, login):
    c = login("a_mgr")
    c.post("/crm/activities/save", data={"partner_id": str(co["pid"]), "contact_id": str(co["contact"]),
                                         "kind": "call", "act_date": "2026-10-01", "subject": "필터대상"})
    c.post("/crm/activities/save", data={"partner_id": str(co["pid"]), "kind": "call",
                                         "act_date": "2026-10-02", "subject": "필터제외"})
    r = c.get(f"/crm/activities?partner_id={co['pid']}&contact_id={co['contact']}")
    assert "필터대상" in r.text
    assert "필터제외" not in r.text


# 영업 캘린더

def test_calendar_month_scoped_and_rep_filter(db, co, login, seed):
    c = login("a_mgr")
    c.post("/crm/activities/save", data={"partner_id": str(co["pid"]), "kind": "call", "act_date": "2026-10-08",
                                         "subject": "A사미팅", "rep_id": str(co["mgr"])})
    db.execute(
        """INSERT INTO crm_activities (company_id, partner_id, kind, act_date, subject, created_by)
           VALUES (?,?,'call','2026-10-08','타사활동',?)""",
        (co["b_cid"], co["other"], co["b_mgr"]))
    db.commit()

    r = c.get("/crm/calendar?view=month&d=2026-10-08")
    assert r.status_code == 200
    assert "A사미팅" in r.text
    assert "타사활동" not in r.text

    r2 = c.get(f"/crm/calendar?view=month&d=2026-10-08&rep={co['wk']}")
    assert "A사미팅" not in r2.text


def test_calendar_shows_pending_next_action(db, co, login):
    c = login("a_mgr")
    c.post("/crm/activities/save", data={"partner_id": str(co["pid"]), "kind": "call", "act_date": "2026-10-01",
                                         "subject": "완료용", "next_date": "2026-10-10", "next_action": "재방문"})
    r = c.get("/crm/calendar?view=month&d=2026-10-08")
    assert "재방문" in r.text


# 영업 통계

def test_stats_lead_conversion_and_win_rate(db, co, login):
    cid = co["cid"]
    db.execute("INSERT INTO crm_leads (company_id, name, source, status, created_at) VALUES (?,?,?,?,?)",
              (cid, "리드1", "홈페이지", "converted", "2026-01-05 10:00:00"))
    db.execute("INSERT INTO crm_leads (company_id, name, source, status, created_at) VALUES (?,?,?,?,?)",
              (cid, "리드2", "홈페이지", "new", "2026-02-05 10:00:00"))
    db.execute("INSERT INTO crm_leads (company_id, name, source, status, created_at) VALUES (?,?,?,?,?)",
              (cid, "리드3", "소개", "lost", "2026-03-05 10:00:00"))
    # 기간 밖 리드는 집계에서 제외됨
    db.execute("INSERT INTO crm_leads (company_id, name, source, status, created_at) VALUES (?,?,?,?,?)",
              (cid, "작년리드", "홈페이지", "converted", "2025-12-01 10:00:00"))
    db.execute("INSERT INTO crm_opps (company_id, title, stage, amount, rep_id, closed_at) VALUES (?,?,?,?,?,?)",
              (cid, "기회1", "won", 1000000, co["mgr"], "2026-02-01"))
    db.execute("INSERT INTO crm_opps (company_id, title, stage, amount, rep_id, closed_at) VALUES (?,?,?,?,?,?)",
              (cid, "기회2", "lost", 500000, co["mgr"], "2026-03-01"))
    db.commit()

    r = login("a_mgr").get("/crm/stats?date_from=2026-01-01&date_to=2026-12-31")
    assert r.status_code == 200
    # 리드 전체 3건(기간 밖 1건 제외), 전환 1건 -> 33.3%
    assert "33.3%" in r.text
    # 담당 수주1 실패1 -> 수주율 50.0%, 수주금액 100만
    assert "50.0%" in r.text
    assert "1,000,000" in r.text


# /erp_scrm 거래처 알림 (core.partner 계약 의존)

def test_erp_scrm_shows_alert_counts(db, co, login):
    cid, uid = co["cid"], co["mgr"]
    pid = _partner(db, cid, "C9", "한도초과", partner_type="customer", credit_limit=100000)
    _slip(db, cid, uid, "2026-09-01", pid, 500000, 0, "S9")
    db.commit()

    r = login("a_mgr").get("/erp_scrm")
    assert r.status_code == 200
    assert "거래처 알림" in r.text
    assert "전체 1곳" in r.text

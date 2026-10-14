import io

import pytest
from openpyxl import load_workbook

from core import partner as ptn


@pytest.fixture
def pco(db, seed):
    a, b = seed["a"], seed["b"]
    pid = db.execute(
        """INSERT INTO partners (code, name, company_id, partner_type, credit_limit, credit_days,
           pay_terms, pay_days) VALUES ('C1','가고객',?,'customer',1000000,30,'days',10)""",
        (a["company"],),
    ).lastrowid
    other = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES ('X1','남의고객',?,'customer')",
        (b["company"],),
    ).lastrowid
    db.commit()
    return {"cid": a["company"], "mgr": a["mgr"], "wk": a["wk"], "b_mgr": b["mgr"], "pid": pid, "other": other}


# 단위 테스트

def test_digits():
    assert ptn.digits("010-1234-5678") == "01012345678"


def test_fmt_phone():
    assert ptn.fmt_phone("01012345678") == "010-1234-5678"
    assert ptn.fmt_phone("0212345678") == "02-1234-5678"
    assert ptn.fmt_phone("") == ""


def test_mask_reg():
    assert ptn.mask_reg("9001011234567") == "900101-1******"
    assert ptn.mask_reg("220-81-62517") == "220-81-62517"


def test_due_date():
    assert ptn.due_date("2026-10-08", "", 0) == "2026-10-08"
    assert ptn.due_date("2026-10-08", "cash", 0) == "2026-10-08"
    assert ptn.due_date("2026-10-08", "days", 10) == "2026-10-18"
    assert ptn.due_date("2026-10-08", "eom", 5) == "2026-11-05"


def test_validate_reg_no():
    assert ptn.validate_reg_no("biz", "2208162517") == ("220-81-62517", None)
    assert ptn.validate_reg_no("biz", "220-81-62518")[1] is not None
    assert ptn.validate_reg_no("biz", "") == ("", None)
    assert ptn.validate_reg_no("rrn", "9001011234567") == ("900101-1234567", None)
    assert ptn.validate_reg_no("rrn", "9001019234567")[1] is not None
    assert ptn.validate_reg_no("foreign", "AB1234") == ("AB1234", None)
    assert ptn.validate_reg_no("foreign", "x" * 21)[1] is not None


# guard()

def test_guard_stop_blocks(db, pco):
    db.execute("UPDATE partners SET trade_status='stop' WHERE id=?", (pco["pid"],))
    db.commit()
    r = ptn.guard(db, pco["cid"], pco["pid"], 1000, "2026-10-08", "견적")
    assert r["block"] and "거래중지" in r["msg"]


def test_guard_hold_warns_without_block(db, pco):
    db.execute("UPDATE partners SET trade_status='hold' WHERE id=?", (pco["pid"],))
    db.commit()
    r = ptn.guard(db, pco["cid"], pco["pid"], 1000, "2026-10-08", "발주")
    assert not r["block"] and "거래보류" in r["msg"]


def test_guard_closed_biz_warns(db, pco):
    db.execute("UPDATE partners SET biz_status='closed', biz_checked_at='2026-01-01' WHERE id=?", (pco["pid"],))
    db.commit()
    r = ptn.guard(db, pco["cid"], pco["pid"], 1000, "2026-10-08", "세금계산서")
    assert not r["block"]
    assert "폐업" in r["msg"] and "2026-01-01" in r["msg"]


def test_guard_combines_with_credit_block(db, pco):
    db.execute("UPDATE client_companies SET credit_limit_mode='block' WHERE id=?", (pco["cid"],))
    db.execute("UPDATE partners SET trade_status='hold' WHERE id=?", (pco["pid"],))
    db.commit()
    r = ptn.guard(db, pco["cid"], pco["pid"], 2000000, "2026-10-08", "출고")
    assert r["block"]
    assert "거래보류" in r["msg"] and "여신한도" in r["msg"]


def test_guard_bad_date_raises(db, pco):
    with pytest.raises(ValueError):
        ptn.guard(db, pco["cid"], pco["pid"], 1000, "bad-date", "견적")


def test_guard_none_when_clean(db, pco):
    assert ptn.guard(db, pco["cid"], pco["pid"], 1000, "2026-10-08", "견적") is None


# 담당자/배송지/계좌 upsert

def test_contacts_upsert_keeps_ids_and_default_primary(db, pco, login):
    c = login("a_mgr")
    r = c.post("/partners/save", data={
        "partner_id": str(pco["pid"]), "code": "C1", "name": "가고객",
        "c_rows": "1,2", "c_name_1": "김담당", "c_active_1": "1",
        "c_name_2": "이담당", "c_active_2": "1",
    }, follow_redirects=False)
    assert r.status_code == 303
    rows = db.execute("SELECT id, name, is_primary FROM partner_contacts WHERE partner_id=? ORDER BY sort",
                      (pco["pid"],)).fetchall()
    assert len(rows) == 2
    assert rows[0]["is_primary"] == 1  # 대표 미지정 시 재직 중인 첫 담당자
    cid1 = rows[0]["id"]

    r = c.post("/partners/save", data={
        "partner_id": str(pco["pid"]), "code": "C1", "name": "가고객",
        "c_rows": "1", "c_id_1": str(cid1), "c_name_1": "김담당수정", "c_active_1": "1",
    }, follow_redirects=False)
    assert r.status_code == 303
    rows = db.execute("SELECT id, name FROM partner_contacts WHERE partner_id=?", (pco["pid"],)).fetchall()
    assert [tuple(x) for x in rows] == [(cid1, "김담당수정")]


def test_contact_removed_but_referenced_becomes_inactive(db, pco, login):
    c = login("a_mgr")
    c.post("/partners/save", data={"partner_id": str(pco["pid"]), "code": "C1", "name": "가고객",
                                   "c_rows": "1", "c_name_1": "김담당", "c_active_1": "1"})
    cid = db.execute("SELECT id FROM partner_contacts WHERE partner_id=?", (pco["pid"],)).fetchone()[0]
    db.execute(
        """INSERT INTO crm_activities (company_id, partner_id, contact_id, kind, act_date, subject)
           VALUES (?,?,?,'call','2026-10-01','x')""", (pco["cid"], pco["pid"], cid))
    db.commit()
    r = c.post("/partners/save", data={"partner_id": str(pco["pid"]), "code": "C1", "name": "가고객", "c_rows": ""},
               follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT is_active FROM partner_contacts WHERE id=?", (cid,)).fetchone()
    assert row["is_active"] == 0


def test_contact_removed_unreferenced_deleted(db, pco, login):
    c = login("a_mgr")
    c.post("/partners/save", data={"partner_id": str(pco["pid"]), "code": "C1", "name": "가고객",
                                   "c_rows": "1", "c_name_1": "김담당", "c_active_1": "1"})
    assert db.execute("SELECT COUNT(*) FROM partner_contacts WHERE partner_id=?", (pco["pid"],)).fetchone()[0] == 1
    c.post("/partners/save", data={"partner_id": str(pco["pid"]), "code": "C1", "name": "가고객", "c_rows": ""})
    assert db.execute("SELECT COUNT(*) FROM partner_contacts WHERE partner_id=?", (pco["pid"],)).fetchone()[0] == 0


def test_bank_default_first_when_unspecified(db, pco, login):
    r = login("a_mgr").post("/partners/save", data={
        "partner_id": str(pco["pid"]), "code": "C1", "name": "가고객",
        "b_rows": "1,2", "b_bank_1": "국민", "b_account_1": "111", "b_bank_2": "신한", "b_account_2": "222",
    }, follow_redirects=False)
    assert r.status_code == 303
    rows = db.execute("SELECT bank, is_default FROM partner_banks WHERE partner_id=? ORDER BY sort",
                      (pco["pid"],)).fetchall()
    assert (rows[0]["bank"], rows[0]["is_default"]) == ("국민", 1)
    assert (rows[1]["bank"], rows[1]["is_default"]) == ("신한", 0)


# 변경이력

def test_history_rows_for_name_rep_trade_bank(db, pco, login):
    login("a_mgr").post("/partners/save", data={
        "partner_id": str(pco["pid"]), "code": "C1", "name": "가고객이름변경", "rep_id": str(pco["wk"]),
        "trade_status": "hold", "b_rows": "1", "b_bank_1": "국민", "b_account_1": "111",
    })
    fields = {r["field"] for r in db.execute(
        "SELECT field FROM partner_history WHERE partner_id=?", (pco["pid"],))}
    assert {"name", "rep_id", "trade_status", "bank"} <= fields


def test_new_partner_has_no_history(db, pco, login):
    login("a_mgr").post("/partners/save", data={"name": "신규무역"})
    pid = db.execute("SELECT id FROM partners WHERE name='신규무역'").fetchone()[0]
    assert db.execute("SELECT COUNT(*) FROM partner_history WHERE partner_id=?", (pid,)).fetchone()[0] == 0


# 권한/테넌트 격리

def test_worker_403_on_save_and_merge(db, pco, login):
    c = login("a_wk")
    assert c.post("/partners/save", data={"name": "워커시도"}).status_code == 403
    assert c.get(f"/partners/{pco['pid']}/edit").status_code == 403
    assert c.get(f"/partners/{pco['pid']}/merge").status_code == 403
    assert c.post(f"/partners/{pco['pid']}/merge", data={"src_id": "1", "confirm": "1"}).status_code == 403


def test_other_company_contact_id_ignored(db, pco, login):
    other_company = db.execute("SELECT company_id FROM partners WHERE id=?", (pco["other"],)).fetchone()[0]
    other_contact = db.execute(
        "INSERT INTO partner_contacts (company_id, partner_id, name) VALUES (?,?,'남의담당')",
        (other_company, pco["other"]),
    ).lastrowid
    db.commit()
    r = login("a_mgr").post("/partners/save", data={
        "partner_id": str(pco["pid"]), "code": "C1", "name": "가고객",
        "c_rows": "1", "c_id_1": str(other_contact), "c_name_1": "가짜", "c_active_1": "1",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT name FROM partner_contacts WHERE id=?", (other_contact,)).fetchone()[0] == "남의담당"
    assert db.execute("SELECT COUNT(*) FROM partner_contacts WHERE partner_id=? AND name='가짜'",
                      (pco["pid"],)).fetchone()[0] == 1


def test_merge_other_company_partner_rejected(db, pco, login):
    r = login("a_mgr").post(f"/partners/{pco['pid']}/merge", data={"src_id": str(pco["other"]), "confirm": "1"})
    assert r.status_code == 400
    assert db.execute("SELECT merged_into FROM partners WHERE id=?", (pco["other"],)).fetchone()[0] is None


def test_contacts_api_404_other_company(db, pco, login):
    c = login("a_mgr")
    assert c.get(f"/api/partners/{pco['other']}/contacts").status_code == 404
    assert c.get(f"/api/partners/{pco['other']}/addrs").status_code == 404


# 통합(merge)

def test_merge_moves_docs_and_slip_lines(db, pco, login):
    cid = pco["cid"]
    b = db.execute("INSERT INTO partners (code, name, company_id, partner_type) VALUES ('C2','나고객',?,'customer')",
                  (cid,)).lastrowid
    qid = db.execute(
        """INSERT INTO quotations (quote_number, partner_id, quote_date, total_amount, tax_amount, company_id)
           VALUES ('QT-9',?,'2026-10-01',1000,100,?)""", (b, cid)).lastrowid
    doc = db.execute(
        """INSERT INTO erp_docs (user_id, doc_type, status, slip_date, slip_no, doc_number, company_id, title)
           VALUES (?,'expense','done','2026-10-01','S9','S9',?,'t')""", (pco["mgr"], cid)).lastrowid
    db.execute(
        """INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner_id)
           VALUES (?,1,'외상매출금','110',5000,0,?)""", (doc, b))
    db.commit()

    r = login("a_mgr").post(f"/partners/{pco['pid']}/merge", data={"src_id": str(b), "confirm": "1"},
                            follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT partner_id FROM quotations WHERE id=?", (qid,)).fetchone()[0] == pco["pid"]
    assert db.execute("SELECT partner_id FROM slip_lines WHERE doc_id=?", (doc,)).fetchone()[0] == pco["pid"]
    row = db.execute("SELECT is_active, trade_status, merged_into FROM partners WHERE id=?", (b,)).fetchone()
    assert (row["is_active"], row["trade_status"], row["merged_into"]) == (0, "stop", pco["pid"])
    hist_fields = {r["field"] for r in db.execute("SELECT field FROM partner_history WHERE partner_id IN (?,?)",
                                                  (pco["pid"], b))}
    assert "merge" in hist_fields


def test_merge_requires_confirm_checkbox(db, pco, login):
    b = db.execute("INSERT INTO partners (code, name, company_id, partner_type) VALUES ('C3','다고객',?,'customer')",
                  (pco["cid"],)).lastrowid
    db.commit()
    r = login("a_mgr").post(f"/partners/{pco['pid']}/merge", data={"src_id": str(b)})
    assert r.status_code == 400
    assert db.execute("SELECT merged_into FROM partners WHERE id=?", (b,)).fetchone()[0] is None


# 경보(alerts)

def test_alerts_over_limit_overdue_closed_bal(db, pco):
    cid = pco["cid"]
    doc = db.execute(
        """INSERT INTO erp_docs (user_id, doc_type, status, slip_date, slip_no, doc_number, company_id, title)
           VALUES (?,'expense','done','2026-08-01','S1','S1',?,'t')""", (pco["mgr"], cid)).lastrowid
    db.execute(
        """INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner_id)
           VALUES (?,1,'외상매출금','110',2000000,0,?)""", (doc, pco["pid"]))
    db.execute("UPDATE partners SET biz_status='closed' WHERE id=?", (pco["pid"],))
    db.commit()
    codes = ptn.alerts(db, cid, "2026-10-08").get(pco["pid"], [])
    assert "over_limit" in codes
    assert "overdue" in codes
    assert "closed_bal" in codes


def test_alerts_skip_inactive_and_merged(db, pco):
    db.execute("UPDATE partners SET is_active=0 WHERE id=?", (pco["pid"],))
    db.commit()
    assert ptn.alerts(db, pco["cid"], "2026-10-08") == {}


# 담당자 목록 전화번호 검색

def test_contact_directory_digit_search(db, pco, login):
    db.execute(
        "INSERT INTO partner_contacts (company_id, partner_id, name, mobile, is_active) VALUES (?,?,'김전화','010-1234-5678',1)",
        (pco["cid"], pco["pid"]))
    db.commit()
    r = login("a_mgr").get("/partners/contacts?q=01012345678")
    assert "김전화" in r.text


# 일괄변경

def test_bulk_trade_status_history_and_foreign_ignored(db, pco, login):
    r = login("a_mgr").post("/partners/bulk", data={
        "ids": [str(pco["pid"]), str(pco["other"])], "action": "trade_status", "value": "hold",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT trade_status FROM partners WHERE id=?", (pco["pid"],)).fetchone()[0] == "hold"
    assert db.execute("SELECT trade_status FROM partners WHERE id=?", (pco["other"],)).fetchone()[0] != "hold"
    hist = db.execute("SELECT field, new FROM partner_history WHERE partner_id=?", (pco["pid"],)).fetchone()
    assert tuple(hist) == ("trade_status", "거래보류")


def test_bulk_requires_editor(db, pco, login):
    r = login("a_wk").post("/partners/bulk", data={
        "ids": [str(pco["pid"])], "action": "trade_status", "value": "hold",
    })
    assert r.status_code == 403


# 엑셀

def test_partners_excel_returns_xlsx(db, pco, login):
    r = login("a_mgr").get("/partners/excel")
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.active["A1"].value == "거래처코드"

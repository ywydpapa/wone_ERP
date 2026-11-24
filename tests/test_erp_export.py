import io
import json
import sqlite3

from openpyxl import load_workbook

from core import invoices
from core.erp_export import EXPORT_SCHEMAS, PRESETS, apply_template, std_lines
from migrate import run_migrations
from tests.conftest import make_partner


def _slip_req(db, seed):
    a = seed["a"]
    req_id = db.execute(
        "INSERT INTO work_requests (company_id, title, task_type, status) VALUES (?, '전표', 'data_entry', 'in_progress')",
        (a["company"],)).lastrowid
    task_id = db.execute(
        "INSERT INTO tasks (work_request_id, title, task_type, status, erp_module) "
        "VALUES (?, '매입', 'data_entry', 'completed', 'slip_purchase')", (req_id,)).lastrowid
    pid = make_partner(db, a["company"], code="P01", biz_no="123-45-67890")
    # 같은 일자 전표 2건 + 다음 일자 1건
    for d in ("2026-11-01", "2026-11-01", "2026-11-02"):
        doc = db.execute(
            "INSERT INTO erp_docs (user_id, doc_type, title, slip_date, slip_type, task_id, slip_no) "
            "VALUES (?, 'slip', '매입', ?, '매입', ?, ?)", (a["wk"], d, task_id, f"S{d}")).lastrowid
        db.execute("INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, partner_id, partner, dept) "
                   "VALUES (?, 1, '원재료', '153', 10000, ?, '거래처P01', '구매팀')", (doc, pid))
        db.execute("INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, credit) "
                   "VALUES (?, 2, '외상매입금', '251', 10000)", (doc,))
    db.commit()
    return req_id


def _sheet(resp):
    ws = load_workbook(io.BytesIO(resp.content)).active
    return [list(r) for r in ws.iter_rows(values_only=True)]


def test_tpl_derived():
    rows = [
        {"doc_id": 1, "slip_date": "2026-11-01", "debit": 500, "credit": 0},
        {"doc_id": 1, "slip_date": "2026-11-01", "debit": 0, "credit": 500},
        {"doc_id": 2, "slip_date": "2026-11-01", "debit": 300, "credit": 0},
        {"doc_id": 3, "slip_date": "2026-11-02", "debit": 0, "credit": 300},
    ]
    tpl = {"columns": json.dumps([
        {"src": "_fixed", "header": "회사코드", "value": "1000"},
        {"src": "slip_date", "fmt": "ymd"},
        {"src": "day_seq"},
        {"src": "dc_type", "codes": ["3", "4"]},
        {"src": "dc_amt"},
    ])}
    headers, lines = apply_template("slip", tpl, rows)
    assert headers == ["회사코드", "전표일자", "일자별 전표순번", "차대구분", "차대 금액"]
    assert lines == [
        ["1000", "20261101", 1, "3", 500],
        ["1000", "20261101", 1, "4", 500],
        ["1000", "20261101", 2, "3", 300],
        ["1000", "20261102", 1, "4", 300],
    ]


def test_std_no_derived():
    headers, _ = std_lines("slip", [])
    assert "차대구분" not in headers
    assert "거래처코드" in headers and "사업자번호" in headers


def test_export_by_set(db, seed, login):
    req_id = _slip_req(db, seed)
    cid = seed["a"]["company"]
    st = login("t_staff")
    r = st.post(f"/platform/export-templates/{cid}/preset", data={"preset": "douzone_icube"},
                follow_redirects=False)
    assert r.status_code == 303
    cols = json.loads(db.execute(
        "SELECT columns FROM export_templates WHERE company_id = ? AND name = '더존 iCUBE'", (cid,)).fetchone()[0])
    cols[0]["value"] = "1000"
    db.execute("UPDATE export_templates SET columns = ? WHERE company_id = ? AND name = '더존 iCUBE'",
               (json.dumps(cols, ensure_ascii=False), cid))
    db.commit()

    ca = login("a_mgr")
    assert "더존 iCUBE 양식" in ca.get(f"/client/requests/{req_id}").text

    rows = _sheet(ca.get(f"/client/requests/{req_id}/export?tpl=더존 iCUBE"))
    assert rows[0][:4] == ["회사코드", "거래일자", "거래순번", "분개라인순번"]
    # 회사코드, 일자, 순번, 라인, 회계단위, 차대, 계정, 사업자번호, 금액
    assert rows[1][:9] == ["1000", "20261101", 1, 1, None, "3", "153", "1234567890", 10000]
    assert rows[2][2] == 1 and rows[2][5] == "4"
    assert rows[3][2] == 2
    assert rows[5][1:3] == ["20261102", 1]

    std = _sheet(ca.get(f"/client/requests/{req_id}/export?tpl="))
    assert "거래처코드" in std[0]
    assert std[1][std[0].index("거래처코드")] == "P01"
    assert std[1][std[0].index("부서")] == "구매팀"


def test_preset_keeps_edit(db, seed, login):
    cid = seed["a"]["company"]
    st = login("t_staff")
    st.post(f"/platform/export-templates/{cid}/preset", data={"preset": "douzone_icube"})
    assert "더존" in st.get(f"/platform/export-templates?company_id={cid}").text
    db.execute("UPDATE export_templates SET columns = '[]' WHERE company_id = ?", (cid,))
    db.commit()
    st.post(f"/platform/export-templates/{cid}/preset", data={"preset": "douzone_icube"})
    assert db.execute("SELECT columns FROM export_templates WHERE company_id = ?", (cid,)).fetchone()[0] == "[]"


def test_save_fixed(db, seed, login):
    cid = seed["a"]["company"]
    st = login("t_staff")
    r = st.post(f"/platform/export-templates/{cid}/slip", data={
        "name": "이카운트", "file_format": "csv",
        "use_slip_date": "1", "ord_slip_date": "2", "header_slip_date": "일자",
        "use_dc_type": "1", "ord_dc_type": "3", "codes_dc_type": "D, C",
        "fix_header": ["회사", ""], "fix_value": ["A1", ""], "fix_ord": ["1", ""],
    }, follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT columns, file_format FROM export_templates WHERE company_id = ? AND name = '이카운트'",
                     (cid,)).fetchone()
    cols = json.loads(row["columns"])
    assert [c["src"] for c in cols] == ["_fixed", "slip_date", "dc_type"]
    assert cols[0]["value"] == "A1" and cols[2]["codes"] == ["D", "C"]
    assert row["file_format"] == "csv"
    assert st.get(f"/platform/export-templates/{cid}/slip?name=이카운트").status_code == 200


def test_migrate_old_tpl(tmp_path):
    path = str(tmp_path / "m.db")
    run_migrations(path, upto=132)
    conn = sqlite3.connect(path)
    cid = conn.execute("INSERT INTO client_companies (name) VALUES ('가')").lastrowid
    conn.execute("INSERT INTO export_templates (company_id, module, columns) VALUES (?, 'slip', '[]')", (cid,))
    conn.commit()
    conn.close()
    run_migrations(path)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT module, name FROM export_templates").fetchall() == [("slip", "기본")]
    conn.close()


def test_client_picks_erp(db, seed, login):
    req_id = _slip_req(db, seed)
    cid = seed["a"]["company"]
    ca = login("a_mgr")
    assert ca.get("/client/settings/export").status_code == 200
    r = ca.post("/client/settings/export", data={
        "erp": "douzone_icube", "douzone_icube_co_cd": "1000", "douzone_icube_div_cd": "1100",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT export_set FROM client_companies WHERE id = ?", (cid,)).fetchone()[0] == "더존 iCUBE"
    assert 'value="1000"' in ca.get("/client/settings/export").text
    assert '<option value="더존 iCUBE" selected' in ca.get(f"/client/requests/{req_id}").text

    rows = _sheet(ca.get(f"/client/requests/{req_id}/export?tpl=더존 iCUBE"))
    assert rows[1][0] == "1000" and rows[1][4] == "1100"

    # 플랫폼 수정분은 고객사 재저장 시에도 유지
    cols = json.loads(db.execute("SELECT columns FROM export_templates WHERE company_id = ?", (cid,)).fetchone()[0])
    cols[-1]["header"] = "적요2"
    db.execute("UPDATE export_templates SET columns = ? WHERE company_id = ?", (json.dumps(cols, ensure_ascii=False), cid))
    db.commit()
    ca.post("/client/settings/export", data={
        "erp": "douzone_icube", "douzone_icube_co_cd": "2000", "douzone_icube_div_cd": "1100"})
    cols = json.loads(db.execute("SELECT columns FROM export_templates WHERE company_id = ?", (cid,)).fetchone()[0])
    assert cols[0]["value"] == "2000" and cols[-1]["header"] == "적요2"

    ca.post("/client/settings/export", data={"erp": "douzone_smarta"})
    assert db.execute("SELECT export_set FROM client_companies WHERE id = ?", (cid,)).fetchone()[0] == "더존 Smart A"
    ca.post("/client/settings/export", data={"erp": "nope"})
    assert db.execute("SELECT export_set FROM client_companies WHERE id = ?", (cid,)).fetchone()[0] == "더존 Smart A"


def test_staff_keeps_input(db, seed, login):
    cid = seed["a"]["company"]
    st = login("t_staff")
    st.post(f"/platform/export-templates/{cid}/preset", data={"preset": "douzone_icube"})
    page = st.get(f"/platform/export-templates/{cid}/slip?name=더존 iCUBE").text
    assert 'name="fix_input" value="co_cd"' in page
    st.post(f"/platform/export-templates/{cid}/slip", data={
        "name": "더존 iCUBE", "use_summary": "1", "ord_summary": "2",
        "fix_header": ["회사코드", ""], "fix_value": ["", ""], "fix_ord": ["1", ""], "fix_input": ["co_cd", ""],
    })
    cols = json.loads(db.execute("SELECT columns FROM export_templates WHERE company_id = ?", (cid,)).fetchone()[0])
    assert cols[0] == {"src": "_fixed", "header": "회사코드", "value": "", "input": "co_cd"}


def test_staff_keeps_card(db, seed, login):
    cid = seed["a"]["company"]
    st = login("t_staff")
    st.post(f"/platform/export-templates/{cid}/preset", data={"preset": "douzone_smarta"})
    page = st.get(f"/platform/export-templates/{cid}/vat?name=더존 Smart A").text
    assert page.count('name="fix_card" value="1"') == 2
    st.post(f"/platform/export-templates/{cid}/vat", data={
        "name": "더존 Smart A", "use_year": "1", "ord_year": "1",
        "fix_header": ["신용카드사명", ""], "fix_value": ["", ""], "fix_ord": ["2", ""],
        "fix_input": ["card_name", ""], "fix_card": ["1", ""],
    })
    cols = json.loads(db.execute("SELECT columns FROM export_templates WHERE company_id = ?", (cid,)).fetchone()[0])
    assert cols[1]["card"] is True

def test_ecount_preset(db, seed):
    srcs = {s for s, _ in EXPORT_SCHEMAS["partner"]["columns"]}
    for c in PRESETS["ecount"]["modules"]["partner"]:
        assert c["src"] == "_fixed" or c["src"] in srcs


def test_smarta_vat(db, seed, login):
    req_id = _slip_req(db, seed)
    a = seed["a"]
    docs = [r[0] for r in db.execute("SELECT id FROM erp_docs WHERE slip_no LIKE 'S2026%' ORDER BY id")]
    pid = db.execute("SELECT partner_id FROM slip_lines WHERE doc_id = ? AND line_no = 1", (docs[0],)).fetchone()[0]
    pname = db.execute("SELECT name FROM partners WHERE id = ?", (pid,)).fetchone()[0]
    invoices.add(db, a["company"], a["wk"], {
        "kind": "매입", "tax_type": "과세", "evidence": "세금계산서", "issue_date": "2026-11-01",
        "partner_id": pid, "supply_amt": 10000, "vat": 1000, "doc_id": docs[0]}, [{"name": "볼트", "supply_amt": 10000}])
    db.commit()

    ca = login("a_mgr")
    ca.post("/client/settings/export", data={"erp": "douzone_smarta"})
    wb = load_workbook(io.BytesIO(ca.get(f"/client/requests/{req_id}/export?tpl=더존 Smart A").content))
    vat = [list(r) for r in wb["매입매출"].iter_rows(values_only=True)]
    assert len(vat[0]) == 18 and vat[0][3] == "매입매출구분(1-매출/2-매입)"
    assert vat[1] == [2026, 11, 1, 2, "51", None, None, None, None, pname, "123-45-67890",
                      10000, 1000, "볼트", 1, "15300", "25100", None]
    # 증빙 연결 전표는 일반전표 시트 제외
    slip = [list(r) for r in wb["전표"].iter_rows(values_only=True)]
    assert len(slip) == 1 + 4

    std = load_workbook(io.BytesIO(ca.get(f"/client/requests/{req_id}/export?tpl=").content))
    assert len(list(std["전표"].iter_rows())) == 1 + 6
    assert len(list(std["매입매출"].iter_rows())) == 2


def test_smarta_card_row(db, seed, login):
    req_id = _slip_req(db, seed)
    a = seed["a"]
    docs = [r[0] for r in db.execute("SELECT id FROM erp_docs WHERE slip_no LIKE 'S2026%' ORDER BY id")]
    pid = db.execute("SELECT partner_id FROM slip_lines WHERE doc_id = ? AND line_no = 1", (docs[0],)).fetchone()[0]
    invoices.add(db, a["company"], a["wk"], {
        "kind": "매입", "tax_type": "과세", "evidence": "세금계산서", "issue_date": "2026-11-01",
        "partner_id": pid, "supply_amt": 10000, "vat": 1000, "doc_id": docs[0]})
    inv = invoices.add(db, a["company"], a["wk"], {
        "kind": "매입", "tax_type": "과세", "evidence": "카드", "issue_date": "2026-11-01", "is_electronic": 0,
        "partner_id": pid, "supply_amt": 10000, "vat": 1000, "doc_id": docs[1]})
    db.execute("INSERT INTO card_txns (company_id, card_no, approve_date, approval_no, tax_invoice_id) "
               "VALUES (?, '1234-5678-9012-3456', '2026-11-01', 'A1', ?)", (a["company"], inv))
    db.commit()

    ca = login("a_mgr")
    ca.post("/client/settings/export", data={"erp": "douzone_smarta", "douzone_smarta_card_cd": "99601",
                                             "douzone_smarta_card_name": "신한카드"})
    wb = load_workbook(io.BytesIO(ca.get(f"/client/requests/{req_id}/export?tpl=더존 Smart A").content))
    vat = [list(r) for r in wb["매입매출"].iter_rows(values_only=True)]
    assert vat[1][4:9] == ["51", None, None, None, None]
    assert vat[2][4:9] == ["57", None, "99601", "신한카드", "1234-5678-9012-3456"]

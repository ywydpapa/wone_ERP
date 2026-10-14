import io

from openpyxl import Workbook


def _xlsx(rows):
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


HEAD = ["작성일자", "승인번호", "공급자사업자등록번호", "상호", "공급받는자사업자등록번호", "상호",
        "합계금액", "공급가액", "세액", "영수/청구", "분류", "종류"]


def _sheet(rows):
    return _xlsx([["아래 목록은 홈택스에서 조회한 세금계산서 내역입니다."], HEAD, *rows])


def test_import_preview_matches_and_unmatched_partner(db, seed, login):
    a = seed["a"]["company"]
    db.execute("INSERT INTO partners (code, name, company_id, partner_type, biz_no) VALUES ('C1','가고객',?,'customer','220-81-62517')", (a,))
    db.commit()
    data = _sheet([
        ["20261008", "AP-0001", "111-22-33333", "가테스트", "220-81-62517", "가고객",
         550000, 500000, 50000, "청구", "세금계산서", "일반"],
        ["20261009", "AP-0002", "111-22-33333", "가테스트", "130-81-00009", "신규거래처",
         300000, 300000, 0, "청구", "계산서", "일반"],
    ])
    r = login("a_mgr").post("/tax-invoices/import", data={"kind": "매출"}, files={"file": ("h.xlsx", data)})
    assert r.status_code == 200
    assert "AP-0001" in r.text and "가고객" in r.text
    assert "AP-0002" in r.text and "신규거래처" in r.text and "거래처 생성" in r.text


def test_import_confirm_posts_sales_slip_and_creates_partner(db, seed, login):
    a = seed["a"]["company"]
    pid = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type, biz_no) VALUES ('C1','가고객',?,'customer','220-81-62517')", (a,)
    ).lastrowid
    db.commit()
    c = login("a_mgr")
    r = c.post("/tax-invoices/import/confirm", data={
        "kind": "매출", "row_count": "1,2",
        "row_1_approval_no": "AP-0001", "row_1_issue_date": "2026-10-08", "row_1_name": "가고객",
        "row_1_biz_no": "220-81-62517", "row_1_supply": "500000", "row_1_vat": "50000",
        "row_1_tax_type": "과세", "row_1_partner_id": str(pid),
        "row_2_approval_no": "AP-0002", "row_2_issue_date": "2026-10-09", "row_2_name": "신규거래처",
        "row_2_biz_no": "130-81-00009", "row_2_supply": "300000", "row_2_vat": "0",
        "row_2_tax_type": "면세", "row_2_partner_id": "", "row_2_create": "1",
    })
    assert r.status_code == 200
    assert "신규 2건" in r.text

    inv1 = db.execute("SELECT * FROM tax_invoices WHERE approval_no='AP-0001'").fetchone()
    assert (inv1["is_electronic"], inv1["source_type"], inv1["tax_type"], inv1["evidence"]) == (1, "hometax", "과세", "세금계산서")
    lines = {l["account_code"]: (l["debit"], l["credit"]) for l in
             db.execute("SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=?", (inv1["doc_id"],))}
    assert lines["110"] == (550000, 0)
    assert lines["401"] == (0, 500000)
    assert lines["255"] == (0, 50000)

    inv2 = db.execute("SELECT * FROM tax_invoices WHERE approval_no='AP-0002'").fetchone()
    assert (inv2["tax_type"], inv2["evidence"]) == ("면세", "계산서")
    new_p = db.execute("SELECT * FROM partners WHERE name='신규거래처'").fetchone()
    assert new_p["partner_type"] == "customer" and new_p["biz_no"] == "130-81-00009"
    assert inv2["partner_id"] == new_p["id"]

    assert db.execute("SELECT COUNT(*) FROM audit_logs WHERE action='invoice_import'").fetchone()[0] == 2


def test_import_confirm_skips_duplicate_approval_no(db, seed, login):
    a = seed["a"]["company"]
    pid = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type, biz_no) VALUES ('C1','가고객',?,'customer','220-81-62517')", (a,)
    ).lastrowid
    db.commit()
    c = login("a_mgr")
    payload = {
        "kind": "매출", "row_count": "1",
        "row_1_approval_no": "AP-0001", "row_1_issue_date": "2026-10-08", "row_1_name": "가고객",
        "row_1_biz_no": "220-81-62517", "row_1_supply": "500000", "row_1_vat": "50000",
        "row_1_tax_type": "과세", "row_1_partner_id": str(pid),
    }
    c.post("/tax-invoices/import/confirm", data=payload)
    assert db.execute("SELECT COUNT(*) FROM tax_invoices").fetchone()[0] == 1

    r = c.post("/tax-invoices/import/confirm", data=payload)
    assert "중복 건너뜀 1건" in r.text
    assert db.execute("SELECT COUNT(*) FROM tax_invoices").fetchone()[0] == 1

    data = _sheet([
        ["20261008", "AP-0001", "111-22-33333", "가테스트", "220-81-62517", "가고객",
         550000, 500000, 50000, "청구", "세금계산서", "일반"],
    ])
    r = c.post("/tax-invoices/import", data={"kind": "매출"}, files={"file": ("h.xlsx", data)})
    assert "중복" in r.text


def test_import_purchase_default_accrued_from_unmatched(db, seed, login):
    data = _sheet([
        ["20261008", "AP-1001", "130-81-00009", "매입처", "111-22-33333", "가테스트",
         110000, 100000, 10000, "청구", "세금계산서", "일반"],
    ])
    r = login("a_mgr").post("/tax-invoices/import", data={"kind": "매입"}, files={"file": ("h.xlsx", data)})
    assert r.status_code == 200
    assert "매입처" in r.text and "거래처 생성" in r.text


def test_manual_tax_invoice_create_unaffected(db, seed, login):
    a = seed["a"]["company"]
    pid = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES ('C1','가고객',?,'customer')", (a,)
    ).lastrowid
    db.commit()
    c = login("a_mgr")
    r = c.post("/tax-invoices", data={
        "kind": "매출", "tax_type": "과세", "evidence": "세금계산서", "issue_date": "2026-10-08",
        "partner_id": str(pid), "acct": "401", "pay": "110",
        "line_count": "1", "item_name_1": "품목", "item_qty_1": "1", "item_price_1": "500000",
        "item_supply_1": "500000", "item_vat_1": "50000",
    }, follow_redirects=False)
    assert r.status_code == 303
    inv = db.execute("SELECT * FROM tax_invoices WHERE partner_id=?", (pid,)).fetchone()
    assert inv["source_type"] == "manual"
    assert db.execute("SELECT COUNT(*) FROM audit_logs WHERE action='invoice_create'").fetchone()[0] == 1

from core import invoices
from tests.conftest import xlsx_bytes as _xlsx

HEAD_FULL = ["승인일자", "승인번호", "가맹점명", "가맹점사업자번호", "공급가액", "부가세", "이용금액", "카드번호"]
HEAD_MIN = ["승인일자", "승인번호", "가맹점명", "이용금액"]


def _card_partner(db, cid, name="신한카드"):
    return db.execute(
        "INSERT INTO partners (company_id, code, name, partner_type) VALUES (?,?,?,'both')",
        (cid, "CARD1", name),
    ).lastrowid


def _txn(db, cid, approval_no="A1", approve_date="2026-10-10", merchant="가게", biz_no="",
         supply=100000, vat=10000, total=110000, status="new"):
    return db.execute(
        """INSERT INTO card_txns (company_id, card_no, approve_date, approval_no, merchant, merchant_biz_no,
               supply_amt, vat, total, status) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (cid, "1234", approve_date, approval_no, merchant, biz_no, supply, vat, total, status),
    ).lastrowid


def test_upload_dedup(db, seed, login):
    a = seed["a"]["company"]
    data = _xlsx([
        HEAD_FULL,
        ["2026-10-01", "AP-1", "가게1", "2208162517", 100000, 10000, 110000, "1234-5678-9012-3456"],
        ["2026-10-02", "AP-2", "가게2", "", 0, 0, 5000, ""],
    ])
    c = login("a_wk")
    r = c.post("/card-txns/upload", files={"file": ("card.xlsx", data)})
    assert r.status_code == 200
    assert "신규 2건, 중복 0건" in r.text

    rows = db.execute("SELECT * FROM card_txns WHERE company_id=? ORDER BY approval_no", (a,)).fetchall()
    assert len(rows) == 2
    assert rows[0]["approve_date"] == "2026-10-01" and rows[0]["merchant_biz_no"] == "220-81-62517"
    assert rows[0]["supply_amt"] == 100000 and rows[0]["vat"] == 10000 and rows[0]["card_no"] == "3456"
    assert rows[1]["total"] == 5000 and rows[1]["vat"] == 0

    r2 = c.post("/card-txns/upload", files={"file": ("card.xlsx", data)})
    assert "신규 0건, 중복 2건" in r2.text
    assert db.execute("SELECT COUNT(*) FROM card_txns WHERE company_id=?", (a,)).fetchone()[0] == 2


def test_upload_no_vat_cols(db, seed, login):
    a = seed["a"]["company"]
    data = _xlsx([HEAD_MIN, ["2026-10-03", "AP-3", "가게3", 30000]])
    c = login("a_wk")
    r = c.post("/card-txns/upload", files={"file": ("card2.xlsx", data)})
    assert "신규 1건, 중복 0건" in r.text
    row = db.execute("SELECT * FROM card_txns WHERE company_id=?", (a,)).fetchone()
    assert row["total"] == 30000 and row["supply_amt"] == 30000 and row["vat"] == 0


def test_deduct_one_slip(db, seed, login):
    a = seed["a"]["company"]
    card_pid = _card_partner(db, a)
    tid = _txn(db, a, biz_no="220-81-62517", merchant="가게1", supply=100000, vat=10000, total=110000)
    db.commit()
    c = login("a_wk")
    r = c.post("/card-txns/process", data={
        "ids": [str(tid)], "card_partner_id": str(card_pid),
        f"account_code_{tid}": "811", f"deduct_{tid}": "1",
    }, follow_redirects=False)
    assert r.status_code == 303

    row = db.execute("SELECT * FROM card_txns WHERE id=?", (tid,)).fetchone()
    assert row["status"] == "posted" and row["tax_invoice_id"] and row["doc_id"]

    inv = db.execute("SELECT * FROM tax_invoices WHERE id=?", (row["tax_invoice_id"],)).fetchone()
    assert (inv["kind"], inv["tax_type"], inv["evidence"], inv["deduct"]) == ("매입", "과세", "카드", 1)
    merchant = db.execute("SELECT * FROM partners WHERE id=?", (inv["partner_id"],)).fetchone()
    assert merchant["biz_no"] == "220-81-62517" and merchant["name"] == "가게1"

    lines = {l["account_code"]: (l["debit"], l["credit"], l["partner_id"]) for l in db.execute(
        "SELECT account_code, debit, credit, partner_id FROM slip_lines WHERE doc_id=?", (row["doc_id"],))}
    assert lines["811"] == (100000, 0, merchant["id"])
    assert lines["135"] == (10000, 0, merchant["id"])
    assert lines["254"] == (0, 110000, card_pid)
    assert len(lines) == 3

    doc = db.execute("SELECT source_type, source_id FROM erp_docs WHERE id=?", (row["doc_id"],)).fetchone()
    assert (doc["source_type"], doc["source_id"]) == ("card", tid)


def test_nondeduct_needs_reason(db, seed, login):
    a = seed["a"]["company"]
    card_pid = _card_partner(db, a)
    tid = _txn(db, a, merchant="식당", supply=100000, vat=10000, total=110000)
    db.commit()
    c = login("a_wk")

    r = c.post("/card-txns/process", data={
        "ids": [str(tid)], "card_partner_id": str(card_pid), f"account_code_{tid}": "812",
    }, follow_redirects=False)
    assert r.status_code == 400
    assert "불공제 사유" in r.json()["error"]

    r2 = c.post("/card-txns/process", data={
        "ids": [str(tid)], "card_partner_id": str(card_pid), f"account_code_{tid}": "812",
        f"nondeduct_reason_{tid}": "4",
    }, follow_redirects=False)
    assert r2.status_code == 303

    row = db.execute("SELECT * FROM card_txns WHERE id=?", (tid,)).fetchone()
    assert row["status"] == "posted" and row["tax_invoice_id"] is None
    assert db.execute("SELECT COUNT(*) FROM tax_invoices WHERE company_id=?", (a,)).fetchone()[0] == 0

    lines = {l["account_code"]: (l["debit"], l["credit"]) for l in db.execute(
        "SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=?", (row["doc_id"],))}
    assert lines["812"] == (110000, 0)
    assert lines["254"] == (0, 110000)
    assert len(lines) == 2


def test_vat_zero_no_invoice(db, seed, login):
    a = seed["a"]["company"]
    card_pid = _card_partner(db, a)
    tid = _txn(db, a, merchant="주유소", supply=50000, vat=0, total=50000)
    db.commit()
    c = login("a_wk")
    r = c.post("/card-txns/process", data={
        "ids": [str(tid)], "card_partner_id": str(card_pid), f"account_code_{tid}": "835", f"deduct_{tid}": "1",
    }, follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT * FROM card_txns WHERE id=?", (tid,)).fetchone()
    assert row["tax_invoice_id"] is None and row["status"] == "posted"


def test_reuse_merchant(db, seed, login):
    a = seed["a"]["company"]
    card_pid = _card_partner(db, a)
    t1 = _txn(db, a, approval_no="A1", biz_no="220-81-62517", merchant="가게1")
    t2 = _txn(db, a, approval_no="A2", biz_no="220-81-62517", merchant="가게1")
    db.commit()
    c = login("a_wk")
    for tid in (t1, t2):
        r = c.post("/card-txns/process", data={
            "ids": [str(tid)], "card_partner_id": str(card_pid),
            f"account_code_{tid}": "811", f"deduct_{tid}": "1",
        }, follow_redirects=False)
        assert r.status_code == 303
    assert db.execute(
        "SELECT COUNT(*) FROM partners WHERE company_id=? AND biz_no='220-81-62517'", (a,)
    ).fetchone()[0] == 1


def test_tenant_isolation(db, seed, login):
    b = seed["b"]["company"]
    card_pid_b = _card_partner(db, b)
    tid_b = _txn(db, b, approval_no="B1")
    db.commit()
    c = login("a_wk")
    r = c.get("/card-txns")
    assert "B1" not in r.text

    r2 = c.post("/card-txns/process", data={
        "ids": [str(tid_b)], "card_partner_id": str(card_pid_b), f"account_code_{tid_b}": "811",
        f"deduct_{tid_b}": "1",
    })
    assert r2.status_code == 400
    assert db.execute("SELECT status FROM card_txns WHERE id=?", (tid_b,)).fetchone()["status"] == "new"


def test_vat_return_card(db, seed, login):
    a = seed["a"]["company"]
    card_pid = _card_partner(db, a)
    tid = _txn(db, a, approve_date="2026-10-15", biz_no="220-81-62517", supply=100000, vat=10000, total=110000)
    db.commit()
    c = login("a_wk")
    r = c.post("/card-txns/process", data={
        "ids": [str(tid)], "card_partner_id": str(card_pid), f"account_code_{tid}": "811", f"deduct_{tid}": "1",
    }, follow_redirects=False)
    assert r.status_code == 303

    ret = invoices.vat_return(db, a, "2026-10-01", "2026-10-31")
    card_gen = next(row for row in ret["buys"] if row[0] == "신용카드/현금영수증 수취분 일반매입")
    assert card_gen[1] == 1 and card_gen[2] == 100000 and card_gen[3] == 10000

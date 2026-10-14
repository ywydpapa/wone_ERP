import pytest


@pytest.fixture
def partners(db, seed):
    ids = {}
    for key in ("a", "b"):
        cid = seed[key]["company"]
        uid = seed[key]["mgr"]
        pid = db.execute(
            "INSERT INTO partners (code, name, company_id, created_by) VALUES (?,?,?,?)",
            (f"{key.upper()}P", f"{key}거래처", cid, uid),
        ).lastrowid

        doc = db.execute(
            """INSERT INTO erp_docs (user_id, doc_type, status, slip_date, slip_no, doc_number, company_id, title)
               VALUES (?,'expense','done','2026-09-01',?,?,?,?)""",
            (uid, f"S-{key}-1", f"S-{key}-1", cid, f"{key}전표"),
        ).lastrowid
        db.execute(
            """INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner_id, summary)
               VALUES (?,1,'외상매출금','110',10000,0,?,?)""",
            (doc, pid, f"{key}매출"),
        )
        db.execute(
            """INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner_id, summary)
               VALUES (?,2,'매출','401',0,10000,?,?)""",
            (doc, pid, f"{key}매출"),
        )

        draft = db.execute(
            """INSERT INTO erp_docs (user_id, doc_type, status, slip_date, slip_no, doc_number, company_id, title)
               VALUES (?,'expense','draft','2026-09-05',?,?,?,?)""",
            (uid, f"S-{key}-2", f"S-{key}-2", cid, f"{key}전표초안"),
        ).lastrowid
        db.execute(
            """INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner_id, summary)
               VALUES (?,1,'외상매출금','110',99999,0,?,?)""",
            (draft, pid, f"{key}미승인"),
        )

        inv = db.execute(
            """INSERT INTO tax_invoices (company_id, kind, issue_date, partner_id, supply_amt, vat, total)
               VALUES (?,'매출','2026-09-01',?,10000,1000,11000)""",
            (cid, pid),
        ).lastrowid
        db.commit()
        ids[key] = {"partner": pid, "doc": doc, "invoice": inv}
    return ids


def test_detail_shows_balance_from_posted_slips_only(partners, login):
    r = login("a_mgr").get(f"/partners/{partners['a']['partner']}")
    assert r.status_code == 200
    assert "10,000" in r.text
    assert "99,999" not in r.text


def test_detail_other_company_404(partners, login):
    r = login("a_mgr").get(f"/partners/{partners['b']['partner']}")
    assert r.status_code == 404


def test_save_redirects_with_saved_flag(partners, login):
    # 다른 탭의 전표 입력 화면이 거래처 변경을 알아채려면 saved=1이 필요함
    c = login("a_mgr")
    pid = partners["a"]["partner"]
    r = c.post("/partners/save", data={"partner_id": str(pid), "code": "AP", "name": "a거래처", "is_active": "1"},
               follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/partners/{pid}?saved=1"


def test_deactivate_hides_from_default_list_and_shows_with_checkbox(db, partners, login):
    c = login("a_mgr")
    pid = partners["a"]["partner"]
    c.post("/partners/save", data={"partner_id": str(pid), "code": "AP", "name": "a거래처", "is_active": "0"})
    assert db.execute("SELECT is_active FROM partners WHERE id=?", (pid,)).fetchone()[0] == 0

    default_list = c.get("/partners").text
    assert "a거래처" not in default_list

    with_inactive = c.get("/partners?include_inactive=1").text
    assert "a거래처" in with_inactive


def test_save_cannot_change_other_company_partner(db, partners, login):
    b = partners["b"]["partner"]
    login("a_mgr").post("/partners/save", data={"partner_id": str(b), "code": "HIJACK", "name": "탈취", "is_active": "1"})
    row = db.execute("SELECT code, name FROM partners WHERE id=?", (b,)).fetchone()
    assert row["code"] == "BP"
    assert row["name"] == "b거래처"

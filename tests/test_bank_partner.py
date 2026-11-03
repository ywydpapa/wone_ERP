import importlib.util
import os

from migrate import run_migrations
from core import books
from core.books import seed_accounts
from tests.conftest import _connect, csrf, seed_companies

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def L(code, dr=0, cr=0, **kw):
    return {"code": code, "debit": dr, "credit": cr, **kw}


def _load_mig():
    path = os.path.join(ROOT, "migrations", "122_bank_partner.py")
    spec = importlib.util.spec_from_file_location("m122", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fill_single_bank(db, seed):
    a = seed["a"]["company"]
    pid = db.execute(
        "INSERT INTO partners (company_id, code, name, kind, partner_type) VALUES (?,'F0001','국민 계좌1','finance','both')",
        (a,),
    ).lastrowid
    db.execute(
        "INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code, partner_id) VALUES (?,'국민','111','계좌1','103',?)",
        (a, pid),
    )
    db.commit()
    lines = [L("813", 500), L("103", cr=500)]
    assert books.fill_bank(db, a, lines) is None
    assert lines[1]["partner_id"] == pid


def test_multi_bank_requires(db, seed):
    a = seed["a"]["company"]
    for no in ("111", "222"):
        pid = db.execute(
            "INSERT INTO partners (company_id, code, name, kind, partner_type) VALUES (?,?,?,'finance','both')",
            (a, f"F{no}", f"국민 계좌{no}"),
        ).lastrowid
        db.execute(
            "INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code, partner_id) VALUES (?,'국민',?,?,'103',?)",
            (a, no, f"계좌{no}", pid),
        )
    db.commit()
    lines = [L("813", 500), L("103", cr=500)]
    assert books.fill_bank(db, a, lines) == "보통예금 계정은 계좌를 선택해 주세요."


def test_fill_overwrites_general(db, seed):
    a = seed["a"]["company"]
    gen_pid = db.execute("INSERT INTO partners (company_id, code, name) VALUES (?,'G0001','일반거래처')", (a,)).lastrowid
    fin_pid = db.execute(
        "INSERT INTO partners (company_id, code, name, kind, partner_type) VALUES (?,'F0001','국민 계좌1','finance','both')",
        (a,),
    ).lastrowid
    db.execute(
        "INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code, partner_id) VALUES (?,'국민','111','계좌1','103',?)",
        (a, fin_pid),
    )
    db.commit()
    lines = [L("813", 500), L("103", cr=500, partner_id=gen_pid)]
    assert books.fill_bank(db, a, lines) is None
    assert lines[1]["partner_id"] == fin_pid


def test_reverse_keeps_partner(db, seed):
    a = seed["a"]["company"]
    uid = seed["a"]["wk"]
    # 계좌 미지정 기존 전표를 그대로 흉내. 이후 계좌가 2개로 늘어도 역분개는 영향받지 않아야 함
    doc = db.execute(
        "INSERT INTO erp_docs (user_id, doc_type, title, status, slip_date, slip_total, company_id, slip_no, doc_number) "
        "VALUES (?,'expense','통신비','done','2026-09-10',500,?,'20260910-00001','20260910-00001')",
        (uid, a),
    ).lastrowid
    db.execute("INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit) VALUES (?,1,'[813] 통신비','813',500,0)", (doc,))
    db.execute("INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit) VALUES (?,2,'[103] 보통예금','103',0,500)", (doc,))
    for no in ("111", "222"):
        db.execute(
            "INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) VALUES (?,'국민',?,?,'103')",
            (a, no, f"계좌{no}"),
        )
    db.commit()

    new_id = books.reverse(db, doc, uid, "2026-09-12")
    line = db.execute("SELECT partner_id FROM slip_lines WHERE doc_id=? AND account_code='103'", (new_id,)).fetchone()
    assert line["partner_id"] is None


def test_cross_company_bank(db, seed):
    a, b = seed["a"]["company"], seed["b"]["company"]
    pid_b = db.execute(
        "INSERT INTO partners (company_id, code, name, kind, partner_type) VALUES (?,'F0001','국민 계좌1','finance','both')",
        (b,),
    ).lastrowid
    db.commit()
    lines = [L("103", 500, partner_id=pid_b), L("401", cr=500)]
    assert books.check_lines(db, a, lines) == "거래처를 찾을 수 없습니다."


def test_migrate_single_bank(tmp_path):
    path = str(tmp_path / "pre122.db")
    run_migrations(path, upto=121)
    conn = _connect(path)
    ids = seed_companies(conn)
    a, b = ids["a"]["company"], ids["b"]["company"]
    seed_accounts(conn, a)
    seed_accounts(conn, b)

    aid = conn.execute(
        "INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) VALUES (?,'국민','111','계좌1','103')", (a,)
    ).lastrowid
    conn.execute(
        "INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) VALUES (?,'국민','222','계좌2','103')", (b,)
    )
    conn.execute(
        "INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) VALUES (?,'신한','333','계좌3','103')", (b,)
    )

    def _doc(book):
        doc = conn.execute(
            "INSERT INTO erp_docs (user_id, doc_type, title, status, slip_date, slip_total, company_id) "
            "VALUES (?,'expense','t','done','2026-09-01',500,?)",
            (ids["staff"], book),
        ).lastrowid
        conn.execute(
            "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit) VALUES (?,1,'[103] 보통예금','103',0,500)",
            (doc,),
        )
        conn.execute(
            "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit) VALUES (?,2,'[401] 상품매출','401',500,0)",
            (doc,),
        )
        return doc

    doc_a, doc_b = _doc(a), _doc(b)
    conn.commit()

    _load_mig().up(conn)

    acct_a = conn.execute("SELECT partner_id FROM bank_accounts WHERE id=?", (aid,)).fetchone()
    line_a = conn.execute("SELECT partner_id FROM slip_lines WHERE doc_id=? AND account_code='103'", (doc_a,)).fetchone()
    assert line_a["partner_id"] == acct_a["partner_id"]

    line_b = conn.execute("SELECT partner_id FROM slip_lines WHERE doc_id=? AND account_code='103'", (doc_b,)).fetchone()
    assert line_b["partner_id"] is None  # 계좌 2개는 보정 대상 아님

    log_a = conn.execute("SELECT summary FROM audit_logs WHERE company_id=? AND action='migrate'", (a,)).fetchone()
    assert "103" in log_a["summary"] and "1건" in log_a["summary"]
    assert conn.execute("SELECT 1 FROM audit_logs WHERE company_id=? AND action='migrate'", (b,)).fetchone() is None

    # 계좌가 없는 계정(401)은 보정 대상 자체가 아님
    line_401 = conn.execute("SELECT partner_id FROM slip_lines WHERE doc_id=? AND account_code='401'", (doc_a,)).fetchone()
    assert line_401["partner_id"] is None
    conn.close()


def test_bank_save_creates_partner(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_wk")
    c.post("/bank-accounts/save", data={
        "csrf_token": csrf(c, "/bank-accounts/new"),
        "bank": "국민은행", "account_no": "123", "name": "법인 보통예금", "account_code": "103",
    }, follow_redirects=False)
    row = db.execute("SELECT * FROM bank_accounts WHERE company_id=?", (a,)).fetchone()
    p = db.execute("SELECT * FROM partners WHERE id=?", (row["partner_id"],)).fetchone()
    assert p["name"] == "국민은행 법인 보통예금" and p["kind"] == "finance" and p["partner_type"] == "both"


def test_bank_save_syncs_partner_name(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_wk")
    c.post("/bank-accounts/save", data={
        "csrf_token": csrf(c, "/bank-accounts/new"),
        "bank": "국민은행", "account_no": "123", "name": "법인 보통예금", "account_code": "103",
    }, follow_redirects=False)
    row = db.execute("SELECT * FROM bank_accounts WHERE company_id=?", (a,)).fetchone()
    c.post("/bank-accounts/save", data={
        "csrf_token": csrf(c, "/bank-accounts/new"),
        "account_id": str(row["id"]),
        "bank": "국민은행", "account_no": "123", "name": "법인 보통예금(변경)", "account_code": "103",
    }, follow_redirects=False)
    p = db.execute("SELECT name FROM partners WHERE id=?", (row["partner_id"],)).fetchone()
    assert p["name"] == "국민은행 법인 보통예금(변경)"


def test_bank_save_syncs_active(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_wk")
    c.post("/bank-accounts/save", data={
        "csrf_token": csrf(c, "/bank-accounts/new"),
        "bank": "국민은행", "account_no": "123", "name": "법인 보통예금", "account_code": "103",
    }, follow_redirects=False)
    row = db.execute("SELECT * FROM bank_accounts WHERE company_id=?", (a,)).fetchone()
    c.post("/bank-accounts/save", data={
        "csrf_token": csrf(c, "/bank-accounts/new"),
        "account_id": str(row["id"]),
        "bank": "국민은행", "account_no": "123", "name": "법인 보통예금", "account_code": "103",
        "is_active": "0",
    }, follow_redirects=False)
    p = db.execute("SELECT is_active, trade_status FROM partners WHERE id=?", (row["partner_id"],)).fetchone()
    assert p["is_active"] == 0 and p["trade_status"] == "stop"

    c.post("/bank-accounts/save", data={
        "csrf_token": csrf(c, "/bank-accounts/new"),
        "account_id": str(row["id"]),
        "bank": "국민은행", "account_no": "123", "name": "법인 보통예금", "account_code": "103",
        "is_active": "1",
    }, follow_redirects=False)
    p = db.execute("SELECT is_active, trade_status FROM partners WHERE id=?", (row["partner_id"],)).fetchone()
    assert p["is_active"] == 1 and p["trade_status"] == "active"

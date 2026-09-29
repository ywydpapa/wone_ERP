import importlib.util
import os

from migrate import run_migrations
from tests.conftest import _connect, seed_companies

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_062():
    path = os.path.join(ROOT, "migrations", "062_books.py")
    spec = importlib.util.spec_from_file_location("m062", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cols(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_fresh_schema(db):
    assert {"company_id", "req_partner", "req_dept"} <= _cols(db, "accounts")
    assert {"company_id", "slip_no", "source_type", "source_id", "reversal_of", "posted_at"} <= _cols(db, "erp_docs")
    assert {"partner_id", "dept", "project_code"} <= _cols(db, "slip_lines")
    assert "company_id" in _cols(db, "partners")
    assert "company_id" in _cols(db, "fi_closings")
    assert "company_id" in _cols(db, "budgets")
    codes = {r["code"] for r in db.execute("SELECT code FROM accounts WHERE company_id=0")}
    assert {"101", "103", "110", "255", "375", "377", "400", "914", "970"} <= codes


def test_backfill(tmp_path):
    path = str(tmp_path / "legacy.db")
    run_migrations(path, upto=61)
    conn = _connect(path)
    ids = seed_companies(conn)
    a = ids["a"]
    conn.execute("INSERT INTO partners (code, name) VALUES ('P1', '가거래처')")
    conn.execute("INSERT INTO partners (code, name, created_by) VALUES ('P2', '나거래처', ?)", (a["wk"],))
    # 근로자 작성 전표 2건(같은 날), staff 작성 1건
    for uid, day in ((a["wk"], "2026-09-01"), (a["wk"], "2026-09-01"), (ids["staff"], "2026-09-02")):
        doc = conn.execute(
            "INSERT INTO erp_docs (user_id, doc_type, title, status, slip_date, slip_total) VALUES (?,?,?,?,?,?)",
            (uid, "expense", "t", "done", day, 1000),
        ).lastrowid
        conn.execute(
            "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner) VALUES (?,1,'[110] 외상매출금','110',1000,0,'나거래처')",
            (doc,),
        )
        conn.execute(
            "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner) VALUES (?,2,'[401] 상품매출','401',0,1000,'')",
            (doc,),
        )
    conn.commit()

    _load_062().up(conn)

    # 001_initial.py가 심는 데모 전표(slip_date='')는 제외하고 이번에 만든 전표만 봄
    docs = conn.execute("SELECT company_id, slip_no, posted_at FROM erp_docs WHERE slip_date != '' ORDER BY id").fetchall()
    assert [d["company_id"] for d in docs] == [a["company"], a["company"], 0]
    assert [d["slip_no"] for d in docs] == ["20260901-00001", "20260901-00002", "20260902-00001"]
    assert all(d["posted_at"] for d in docs)
    seq = conn.execute("SELECT last_no FROM slip_seqs WHERE company_id=? AND slip_date='2026-09-01'", (a["company"],)).fetchone()
    assert seq["last_no"] == 2
    p2 = conn.execute("SELECT id, company_id FROM partners WHERE code='P2'").fetchone()
    assert p2["company_id"] == a["company"]
    assert conn.execute("SELECT company_id FROM partners WHERE code='P1'").fetchone()["company_id"] == 0
    # A사 전표의 거래처 텍스트는 A사 거래처로 매칭
    pid = conn.execute(
        "SELECT l.partner_id FROM slip_lines l JOIN erp_docs d ON d.id=l.doc_id WHERE d.company_id=? AND l.partner='나거래처' LIMIT 1",
        (a["company"],),
    ).fetchone()["partner_id"]
    assert pid == p2["id"]
    # 회사마다 계정 복사
    cnt = conn.execute("SELECT COUNT(*) FROM accounts WHERE company_id=?", (a["company"],)).fetchone()[0]
    base = conn.execute("SELECT COUNT(*) FROM accounts WHERE company_id=0").fetchone()[0]
    assert cnt == base > 70
    conn.close()

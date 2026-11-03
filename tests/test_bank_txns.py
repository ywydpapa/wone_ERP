import csv
import io
import json
import re

from core import bankfile, books
from routers import erp_bank
from tests.conftest import xlsx_bytes


def L(code, dr=0, cr=0, **kw):
    return {"code": code, "debit": dr, "credit": cr, **kw}


def _txn(db, cid, acct, amt_in=0, amt_out=0, counterparty="", memo="", txn_at="2026-10-10",
         balance=None, status="미처리"):
    h = f"{acct}|{txn_at}|{amt_in}|{amt_out}|{counterparty}|{memo}|{status}"
    return db.execute(
        """INSERT INTO bank_txns (company_id, bank_account_id, txn_at, memo, counterparty, amt_in, amt_out,
               balance, hash, status, uploaded_at) VALUES (?,?,?,?,?,?,?,?,?,?,'2026-10-10')""",
        (cid, acct, txn_at, memo, counterparty, amt_in, amt_out, balance, h, status),
    ).lastrowid


def _acct(db, cid, account_no="111"):
    pid = db.execute(
        "INSERT INTO partners (company_id, code, name, kind, partner_type) VALUES (?,?,?,'finance','both')",
        (cid, f"F{account_no}", f"국민은행 법인계좌{account_no}"),
    ).lastrowid
    aid = db.execute(
        "INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code, partner_id) VALUES (?,?,?,?,?,?)",
        (cid, "국민은행", account_no, "법인계좌", "103", pid),
    ).lastrowid
    db.commit()
    return aid


GUIDE = ["내려받은 거래내역입니다.", "문의: 고객센터"]


def test_upload_kb_preset(db, seed, login):
    a = seed["a"]["company"]
    acct = _acct(db, a)
    data = xlsx_bytes([
        GUIDE, [],
        ["거래일시", "적요", "보낸분/받는분", "출금액", "입금액", "잔액"],
        ["2026.10.01 13:22:11", "자동이체", "홍길동", 0, 100000, 100000],
        ["2026.10.02", "카드결제", "", 30000, 0, 70000],
        ["합계", "", "", 30000, 100000, ""],
    ])
    c = login("a_wk")
    r = c.post("/bank-txns/upload", data={"account_id": str(acct)}, files={"file": ("kb.xlsx", data)})
    assert r.status_code == 200
    assert "신규 2건, 중복 0건" in r.text

    rows = db.execute("SELECT * FROM bank_txns WHERE bank_account_id=? ORDER BY id", (acct,)).fetchall()
    assert len(rows) == 2
    assert rows[0]["txn_at"] == "2026-10-01 13:22:11"
    assert rows[0]["amt_in"] == 100000 and rows[0]["amt_out"] == 0 and rows[0]["balance"] == 100000
    assert rows[1]["txn_at"] == "2026-10-02"
    assert rows[1]["amt_out"] == 30000 and rows[1]["balance"] == 70000

    assert db.execute("SELECT import_preset FROM bank_accounts WHERE id=?", (acct,)).fetchone()[0] == "kb"


def test_reupload_same_file_skips_duplicates(db, seed, login):
    a = seed["a"]["company"]
    acct = _acct(db, a)
    data = xlsx_bytes([
        GUIDE, [],
        ["거래일시", "적요", "보낸분/받는분", "출금액", "입금액", "잔액"],
        ["2026.10.01 13:22:11", "자동이체", "홍길동", 0, 100000, 100000],
        ["2026.10.02", "카드결제", "", 30000, 0, 70000],
    ])
    c = login("a_wk")
    c.post("/bank-txns/upload", data={"account_id": str(acct)}, files={"file": ("kb.xlsx", data)})
    r = c.post("/bank-txns/upload", data={"account_id": str(acct)}, files={"file": ("kb.xlsx", data)})
    assert "신규 0건, 중복 2건" in r.text
    assert db.execute("SELECT COUNT(*) FROM bank_txns WHERE bank_account_id=?", (acct,)).fetchone()[0] == 2


def test_upload_shinhan_preset(db, seed, login):
    a = seed["a"]["company"]
    acct = _acct(db, a)
    data = xlsx_bytes([
        GUIDE, [],
        ["거래일자", "적요", "내용", "출금", "입금", "잔액"],
        ["2026-10-03", "급여", "월급", 0, 2000000, 2500000],
    ])
    c = login("a_wk")
    c.post("/bank-txns/upload", data={"account_id": str(acct)}, files={"file": ("shinhan.xlsx", data)})
    row = db.execute("SELECT * FROM bank_txns WHERE bank_account_id=?", (acct,)).fetchone()
    assert row["txn_at"] == "2026-10-03"
    assert row["amt_in"] == 2000000 and row["balance"] == 2500000
    assert db.execute("SELECT import_preset FROM bank_accounts WHERE id=?", (acct,)).fetchone()[0] == "shinhan"


def test_upload_woori_preset(db, seed, login):
    a = seed["a"]["company"]
    acct = _acct(db, a)
    data = xlsx_bytes([
        GUIDE, [],
        ["거래일시", "기재내용", "찾으신금액", "맡기신금액", "잔액"],
        ["2026/10/04", "이체", "50,000", "-", "450000"],
    ])
    c = login("a_wk")
    c.post("/bank-txns/upload", data={"account_id": str(acct)}, files={"file": ("woori.xlsx", data)})
    row = db.execute("SELECT * FROM bank_txns WHERE bank_account_id=?", (acct,)).fetchone()
    assert row["txn_at"] == "2026-10-04"
    assert row["amt_out"] == 50000 and row["amt_in"] == 0 and row["balance"] == 450000
    assert db.execute("SELECT import_preset FROM bank_accounts WHERE id=?", (acct,)).fetchone()[0] == "woori"


def test_upload_hana_preset(db, seed, login):
    a = seed["a"]["company"]
    acct = _acct(db, a)
    data = xlsx_bytes([
        GUIDE, [],
        ["거래일시", "적요", "출금", "입금", "잔액"],
        ["20261005", "이체", 0, 10000, 10000],
    ])
    c = login("a_wk")
    c.post("/bank-txns/upload", data={"account_id": str(acct)}, files={"file": ("hana.xlsx", data)})
    row = db.execute("SELECT * FROM bank_txns WHERE bank_account_id=?", (acct,)).fetchone()
    assert row["txn_at"] == "2026-10-05"
    assert row["amt_in"] == 10000
    assert db.execute("SELECT import_preset FROM bank_accounts WHERE id=?", (acct,)).fetchone()[0] == "hana"


def test_upload_nh_preset(db, seed, login):
    a = seed["a"]["company"]
    acct = _acct(db, a)
    data = xlsx_bytes([
        GUIDE, [],
        ["거래일자", "거래내용", "출금금액", "입금금액", "거래후잔액"],
        ["2026-10-06", "이자", 0, 500, 900500],
    ])
    c = login("a_wk")
    c.post("/bank-txns/upload", data={"account_id": str(acct)}, files={"file": ("nh.xlsx", data)})
    row = db.execute("SELECT * FROM bank_txns WHERE bank_account_id=?", (acct,)).fetchone()
    assert row["txn_at"] == "2026-10-06"
    assert row["amt_in"] == 500 and row["balance"] == 900500
    assert db.execute("SELECT import_preset FROM bank_accounts WHERE id=?", (acct,)).fetchone()[0] == "nh"


def test_csv_cp949(db, seed, login):
    a = seed["a"]["company"]
    acct = _acct(db, a)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["거래일시", "적요", "출금", "입금", "잔액"])
    w.writerow(["2026-10-07", "이체", "0", "15000", "115000"])
    data = buf.getvalue().encode("cp949")
    c = login("a_wk")
    r = c.post("/bank-txns/upload", data={"account_id": str(acct)}, files={"file": ("hana.csv", data)})
    assert "신규 1건, 중복 0건" in r.text
    row = db.execute("SELECT * FROM bank_txns WHERE bank_account_id=?", (acct,)).fetchone()
    assert row["amt_in"] == 15000 and row["balance"] == 115000


def test_header_mismatch_manual_mapping(db, seed, login, monkeypatch, tmp_path):
    monkeypatch.setattr(erp_bank, "BANK_TMP_DIR", str(tmp_path))
    a = seed["a"]["company"]
    acct = _acct(db, a)
    data = xlsx_bytes([
        GUIDE, [],
        ["Date", "Memo", "CashIn", "CashOut", "Bal"],
        ["2026-10-08", "비고", 20000, 0, 80000],
    ])
    c = login("a_wk")
    r = c.post("/bank-txns/upload", data={"account_id": str(acct)}, files={"file": ("unknown.xlsx", data)})
    assert r.status_code == 200
    assert "직접 매핑" in r.text
    assert db.execute("SELECT COUNT(*) FROM bank_txns").fetchone()[0] == 0

    token = re.search(r'name="token" value="([0-9a-f]{32})"', r.text).group(1)
    ext = re.search(r'name="ext" value="([^"]+)"', r.text).group(1)
    assert ext == ".xlsx"
    assert (tmp_path / f"{token}.xlsx").exists()

    r2 = c.post("/bank-txns/upload/map", data={
        "token": token, "ext": ext, "account_id": str(acct), "header_row": "2",
        "date_col": "0", "amt_in_col": "2", "amt_out_col": "3",
        "memo_col": "1", "party_col": "", "balance_col": "4",
    })
    assert "신규 1건, 중복 0건" in r2.text
    assert not (tmp_path / f"{token}.xlsx").exists()

    row = db.execute("SELECT * FROM bank_txns WHERE bank_account_id=?", (acct,)).fetchone()
    assert row["txn_at"] == "2026-10-08"
    assert row["amt_in"] == 20000 and row["amt_out"] == 0 and row["balance"] == 80000
    assert row["memo"] == "비고"

    acct_row = db.execute("SELECT import_preset, column_map FROM bank_accounts WHERE id=?", (acct,)).fetchone()
    assert acct_row["import_preset"] == "generic"
    assert json.loads(acct_row["column_map"]) == {
        "date": "Date", "amt_in": "CashIn", "amt_out": "CashOut", "memo": "Memo", "balance": "Bal",
    }


def test_no_balance_dup_saved(db, seed, login):
    # 카드사 내역처럼 잔액 미매핑 시 동일 적요/금액 거래가 여러 건이어도 전부 저장
    a = seed["a"]["company"]
    acct = _acct(db, a)
    rows = [
        ["2026-10-11", "카드결제", 0, 5000],
        ["2026-10-11", "카드결제", 0, 5000],
    ]
    cmap = {"date": 0, "memo": 1, "amt_out": 2, "amt_in": 3}
    added, dup = erp_bank._import_rows(db, a, seed["a"]["wk"], acct, rows, cmap)
    db.commit()
    assert added == 2 and dup == 0
    assert db.execute("SELECT COUNT(*) FROM bank_txns WHERE bank_account_id=?", (acct,)).fetchone()[0] == 2

    added2, dup2 = erp_bank._import_rows(db, a, seed["a"]["wk"], acct, rows, cmap)
    assert added2 == 0 and dup2 == 2


def test_hash_seq0_legacy(db, seed, login):
    # 순번 0은 기존 해시 규칙과 동일해야 재업로드 시 기존 데이터와 중복 판정 유지
    a = seed["a"]["company"]
    acct = _acct(db, a)
    rows = [["2026-10-12", "이체", 0, 1000]]
    cmap = {"date": 0, "memo": 1, "amt_out": 2, "amt_in": 3}
    erp_bank._import_rows(db, a, seed["a"]["wk"], acct, rows, cmap)
    db.commit()
    t = bankfile.parse(rows, cmap)[0]
    saved_hash = db.execute("SELECT hash FROM bank_txns WHERE bank_account_id=?", (acct,)).fetchone()[0]
    assert saved_hash == bankfile.txn_hash(acct, t)


def test_other_company_account_is_404(db, seed, login):
    b = seed["b"]["company"]
    other_acct = _acct(db, b, account_no="999")
    c = login("a_wk")
    data = xlsx_bytes([["거래일시", "적요", "출금", "입금", "잔액"], ["2026-10-09", "x", 0, 1000, 1000]])
    r = c.post("/bank-txns/upload", data={"account_id": str(other_acct)}, files={"file": ("x.xlsx", data)})
    assert r.status_code == 404


def test_match_rule_prefers_longest_keyword():
    rules = [
        {"keyword": "홍길동", "account_code": "401", "partner_id": None},
        {"keyword": "홍길동상사", "account_code": "108", "partner_id": None},
    ]
    m = erp_bank.match_rule(rules, "자동이체 홍길동상사 입금")
    assert m["account_code"] == "108"


def test_post_slips_marks_processed(db, seed, login):
    a = seed["a"]["company"]
    acct = _acct(db, a)
    tid = _txn(db, a, acct, amt_in=100000, counterparty="홍길동")
    db.commit()
    c = login("a_wk")
    r = c.post("/bank-txns/slips", data={"ids": [str(tid)], f"account_code_{tid}": "401"},
               follow_redirects=False)
    assert r.status_code == 303

    row = db.execute("SELECT status, doc_id FROM bank_txns WHERE id=?", (tid,)).fetchone()
    assert row["status"] == "처리"
    lines = {l["account_code"]: (l["debit"], l["credit"]) for l in db.execute(
        "SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=?", (row["doc_id"],))}
    assert lines["103"] == (100000, 0)
    assert lines["401"] == (0, 100000)


def test_txn_slip_bank_partner(db, seed, login):
    a = seed["a"]["company"]
    acct1 = _acct(db, a, "111")
    acct2 = _acct(db, a, "222")
    pid1 = db.execute(
        "INSERT INTO partners (company_id, code, name, kind, partner_type) VALUES (?,'F0001','계좌1','finance','both')",
        (a,),
    ).lastrowid
    pid2 = db.execute(
        "INSERT INTO partners (company_id, code, name, kind, partner_type) VALUES (?,'F0002','계좌2','finance','both')",
        (a,),
    ).lastrowid
    db.execute("UPDATE bank_accounts SET partner_id=? WHERE id=?", (pid1, acct1))
    db.execute("UPDATE bank_accounts SET partner_id=? WHERE id=?", (pid2, acct2))
    tid = _txn(db, a, acct2, amt_in=100000, counterparty="홍길동")
    db.commit()
    c = login("a_wk")
    r = c.post("/bank-txns/slips", data={"ids": [str(tid)], f"account_code_{tid}": "401"},
               follow_redirects=False)
    assert r.status_code == 303

    doc_id = db.execute("SELECT doc_id FROM bank_txns WHERE id=?", (tid,)).fetchone()["doc_id"]
    line = db.execute("SELECT partner_id FROM slip_lines WHERE doc_id=? AND account_code='103'", (doc_id,)).fetchone()
    assert line["partner_id"] == pid2


def test_post_slips_requires_partner(db, seed, login):
    a = seed["a"]["company"]
    acct = _acct(db, a)
    tid = _txn(db, a, acct, amt_in=50000, counterparty="무배정")
    db.commit()
    c = login("a_wk")
    r = c.post("/bank-txns/slips", data={"ids": [str(tid)], f"account_code_{tid}": "110"})
    assert r.status_code == 400
    assert "2026-10-10" in r.json()["error"]
    assert db.execute("SELECT status FROM bank_txns WHERE id=?", (tid,)).fetchone()[0] == "미처리"
    assert db.execute("SELECT COUNT(*) FROM slip_lines").fetchone()[0] == 0


def test_rule_hit_cnt_increments(db, seed, login):
    a = seed["a"]["company"]
    acct = _acct(db, a)
    db.execute("INSERT INTO txn_rules (company_id, keyword, account_code, hit_cnt) VALUES (?,?,?,0)",
              (a, "홍길동", "401"))
    tid = _txn(db, a, acct, amt_in=10000, counterparty="홍길동")
    db.commit()
    c = login("a_wk")
    r = c.post("/bank-txns/slips", data={"ids": [str(tid)], f"account_code_{tid}": "401"},
               follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT hit_cnt FROM txn_rules WHERE company_id=? AND keyword='홍길동'",
                      (a,)).fetchone()[0] == 1


def test_save_rule_creates_rule(db, seed, login):
    a = seed["a"]["company"]
    acct = _acct(db, a)
    tid = _txn(db, a, acct, amt_out=20000, counterparty="새거래처")
    db.commit()
    c = login("a_wk")
    r = c.post("/bank-txns/slips", data={
        "ids": [str(tid)], f"account_code_{tid}": "821", f"save_rule_{tid}": "1"},
        follow_redirects=False)
    assert r.status_code == 303
    rule = db.execute("SELECT account_code FROM txn_rules WHERE company_id=? AND keyword='새거래처'",
                      (a,)).fetchone()
    assert rule["account_code"] == "821"


def test_exclude_patch_sets_status(db, seed, login):
    a = seed["a"]["company"]
    acct = _acct(db, a)
    tid = _txn(db, a, acct, amt_in=5000, counterparty="제외대상")
    db.commit()
    c = login("a_wk")
    r = c.request("PATCH", "/bank-txns", data={"ids": [str(tid)], "status": "제외"})
    assert r.status_code == 200
    assert db.execute("SELECT status FROM bank_txns WHERE id=?", (tid,)).fetchone()[0] == "제외"


def test_balance_recon_matches_pre_created(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    acct = _acct(db, a)
    books.post(db, a, uid, "2026-09-01", [L("103", dr=50000), L("401", cr=50000)], "이전매출", "manual")
    db.commit()
    tid = _txn(db, a, acct, amt_in=100000, counterparty="대사거래", balance=150000, txn_at="2026-10-10")
    db.commit()
    c = login("a_wk")
    r = c.post("/bank-txns/slips", data={"ids": [str(tid)], f"account_code_{tid}": "401"},
               follow_redirects=False)
    assert r.status_code == 303

    r2 = c.get(f"/bank-txns?account_id={acct}&status=")
    assert "150,000" in r2.text


def test_recon_per_bank(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    acct1 = _acct(db, a, "111")
    acct2 = _acct(db, a, "222")
    pid1 = db.execute("SELECT partner_id FROM bank_accounts WHERE id=?", (acct1,)).fetchone()[0]
    pid2 = db.execute("SELECT partner_id FROM bank_accounts WHERE id=?", (acct2,)).fetchone()[0]
    books.post(db, a, uid, "2026-09-01", [L("103", dr=50000, partner_id=pid1), L("401", cr=50000)], "매출1", "manual")
    books.post(db, a, uid, "2026-09-01", [L("103", dr=30000, partner_id=pid2), L("401", cr=30000)], "매출2", "manual")
    db.commit()
    _txn(db, a, acct1, amt_in=0, counterparty="대사", balance=50000, txn_at="2026-10-10")
    db.commit()
    c = login("a_wk")
    r = c.get(f"/bank-txns?account_id={acct1}&status=")
    assert "50,000" in r.text
    assert "80,000" not in r.text


def test_recon_unmatched(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    acct = _acct(db, a)
    gpid = db.execute("INSERT INTO partners (company_id, code, name) VALUES (?,'G1','일반거래처')", (a,)).lastrowid
    books.post(db, a, uid, "2026-09-01", [L("103", dr=20000, partner_id=gpid), L("401", cr=20000)],
              "미지정매출", "manual", keep_lines=True)
    db.commit()
    _txn(db, a, acct, amt_in=0, counterparty="대사", balance=0, txn_at="2026-10-10")
    db.commit()
    c = login("a_wk")
    r = c.get(f"/bank-txns?account_id={acct}&status=")
    assert "계좌 미지정" in r.text
    assert "20,000" in r.text


def test_list_shows_settle_link(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    acct = _acct(db, a)
    pid = db.execute(
        "INSERT INTO partners (code, name, company_id, is_active) VALUES ('C9','수금거래처',?,1)", (a,)
    ).lastrowid
    books.post(db, a, uid, "2026-09-01",
              [L("110", dr=100000, partner_id=pid), L("401", cr=100000)], "매출", "manual")
    db.commit()
    tid = _txn(db, a, acct, amt_in=100000, counterparty="수금거래처")
    db.commit()
    c = login("a_wk")
    r = c.get(f"/bank-txns?account_id={acct}")
    assert r.status_code == 200
    assert f"bank_txn_id={tid}" in r.text
    assert "수금 처리" in r.text


def test_bank_txn_id_other_company(db, seed, login):
    b = seed["b"]["company"]
    b_acct = _acct(db, b, account_no="888")
    tid = _txn(db, b, b_acct, amt_in=1000, counterparty="타사")
    db.commit()
    a = seed["a"]["company"]
    pid = db.execute(
        "INSERT INTO partners (code, name, company_id, is_active) VALUES ('C8','거래처',?,1)", (a,)
    ).lastrowid
    db.commit()
    c = login("a_wk")
    r = c.get(f"/settlements/new?kind=수금&partner_id={pid}&bank_txn_id={tid}")
    assert r.status_code == 404

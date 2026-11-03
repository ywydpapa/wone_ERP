from core import audit, books
from core.tz import now_kst

RECV_STATUS = {"held": "보유", "collected": "만기결제", "discounted": "할인", "endorsed": "배서양도",
               "dishonored": "부도", "canceled": "취소"}
PAY_STATUS = {"issued": "발행", "paid": "결제", "canceled": "취소"}
STATUS = {"recv": RECV_STATUS, "pay": PAY_STATUS}
RECV_ACCT, PAY_ISSUE_ACCT = "111", "252"


def _get(conn, book, note_id):
    n = conn.execute("SELECT * FROM notes WHERE id=? AND company_id=?", (note_id, book)).fetchone()
    if not n:
        raise LookupError
    return n


def _bank(conn, book, bank_account_id):
    bank = conn.execute(
        "SELECT account_code, partner_id FROM bank_accounts WHERE id=? AND company_id=? AND is_active=1",
        (bank_account_id, book),
    ).fetchone()
    if not bank:
        raise ValueError("계좌를 선택해 주세요.")
    return bank


def _close(conn, book, uid, n, status, action_date, lines, summary):
    doc_id = books.post(conn, book, uid, action_date, lines, summary, "note", n["id"])
    conn.execute(
        "UPDATE notes SET status=?, close_doc_id=?, close_date=? WHERE id=?",
        (status, doc_id, action_date, n["id"]),
    )
    audit.log(conn, uid, "note_process", "note", n["id"], f"{summary} ({status})", company_id=book)
    return doc_id


def receive(conn, book, uid, f):
    p = conn.execute("SELECT name FROM partners WHERE id=? AND company_id=?", (f["partner_id"], book)).fetchone()
    if not p:
        raise LookupError
    if f["amount"] <= 0:
        raise ValueError("금액을 입력해 주세요.")
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    nid = conn.execute(
        """INSERT INTO notes (company_id, kind, note_no, partner_id, amount, issue_date, due_date, bank,
               is_electronic, status, memo, created_by, created_at)
           VALUES (?,'recv',?,?,?,?,?,?,?,'held',?,?,?)""",
        (book, f["note_no"], f["partner_id"], f["amount"], f["issue_date"], f["due_date"], f.get("bank", ""),
         1 if f.get("is_electronic") else 0, f.get("memo", ""), uid, now),
    ).lastrowid
    summary = f"{p['name']} 받을어음 수취 {f['note_no']}"
    lines = [
        {"code": RECV_ACCT, "debit": f["amount"], "partner_id": f["partner_id"], "summary": summary},
        {"code": "110", "credit": f["amount"], "partner_id": f["partner_id"], "summary": summary},
    ]
    doc_id = books.post(conn, book, uid, f["issue_date"], lines, summary, "note", nid)
    conn.execute("UPDATE notes SET issue_doc_id=? WHERE id=?", (doc_id, nid))
    audit.log(conn, uid, "note_receive", "note", nid, f"{summary} {f['amount']:,}", company_id=book)
    return nid


def issue(conn, book, uid, f):
    p = conn.execute("SELECT name FROM partners WHERE id=? AND company_id=?", (f["partner_id"], book)).fetchone()
    if not p:
        raise LookupError
    if f["amount"] <= 0:
        raise ValueError("금액을 입력해 주세요.")
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    nid = conn.execute(
        """INSERT INTO notes (company_id, kind, note_no, partner_id, amount, issue_date, due_date, bank,
               is_electronic, status, memo, created_by, created_at)
           VALUES (?,'pay',?,?,?,?,?,?,?,'issued',?,?,?)""",
        (book, f["note_no"], f["partner_id"], f["amount"], f["issue_date"], f["due_date"], f.get("bank", ""),
         1 if f.get("is_electronic") else 0, f.get("memo", ""), uid, now),
    ).lastrowid
    summary = f"{p['name']} 지급어음 발행 {f['note_no']}"
    lines = [
        {"code": "251", "debit": f["amount"], "partner_id": f["partner_id"], "summary": summary},
        {"code": PAY_ISSUE_ACCT, "credit": f["amount"], "partner_id": f["partner_id"], "summary": summary},
    ]
    doc_id = books.post(conn, book, uid, f["issue_date"], lines, summary, "note", nid)
    conn.execute("UPDATE notes SET issue_doc_id=? WHERE id=?", (doc_id, nid))
    audit.log(conn, uid, "note_issue", "note", nid, f"{summary} {f['amount']:,}", company_id=book)
    return nid


def collect(conn, book, uid, note_id, action_date, bank_account_id):
    n = _get(conn, book, note_id)
    if n["kind"] != "recv" or n["status"] != "held":
        raise ValueError("보유 중인 받을어음만 처리할 수 있습니다.")
    bank = _bank(conn, book, bank_account_id)
    summary = f"{n['note_no']} 받을어음 만기결제"
    lines = [
        {"code": bank["account_code"], "debit": n["amount"], "partner_id": bank["partner_id"], "summary": summary},
        {"code": RECV_ACCT, "credit": n["amount"], "partner_id": n["partner_id"], "summary": summary},
    ]
    return _close(conn, book, uid, n, "collected", action_date, lines, summary)


# 받을어음 할인(매각거래). 실수령액은 계좌 입금, 할인료는 매출채권처분손실
def discount(conn, book, uid, note_id, action_date, bank_account_id, fee):
    n = _get(conn, book, note_id)
    if n["kind"] != "recv" or n["status"] != "held":
        raise ValueError("보유 중인 받을어음만 처리할 수 있습니다.")
    if fee < 0 or fee > n["amount"]:
        raise ValueError("할인료를 확인해 주세요.")
    bank = _bank(conn, book, bank_account_id)
    proceeds = n["amount"] - fee
    summary = f"{n['note_no']} 받을어음 할인"
    lines = [{"code": bank["account_code"], "debit": proceeds, "partner_id": bank["partner_id"], "summary": summary}]
    if fee:
        lines.append({"code": "956", "debit": fee, "summary": summary})
    lines.append({"code": RECV_ACCT, "credit": n["amount"], "partner_id": n["partner_id"], "summary": summary})
    return _close(conn, book, uid, n, "discounted", action_date, lines, summary)


# 받을어음 배서양도. 피배서 거래처의 외상매입금과 상계
def endorse(conn, book, uid, note_id, action_date, endorsee_id):
    n = _get(conn, book, note_id)
    if n["kind"] != "recv" or n["status"] != "held":
        raise ValueError("보유 중인 받을어음만 처리할 수 있습니다.")
    p = conn.execute("SELECT name FROM partners WHERE id=? AND company_id=?", (endorsee_id, book)).fetchone()
    if not p:
        raise LookupError
    summary = f"{n['note_no']} 받을어음 배서양도 ({p['name']})"
    lines = [
        {"code": "251", "debit": n["amount"], "partner_id": endorsee_id, "summary": summary},
        {"code": RECV_ACCT, "credit": n["amount"], "partner_id": n["partner_id"], "summary": summary},
    ]
    doc_id = _close(conn, book, uid, n, "endorsed", action_date, lines, summary)
    conn.execute("UPDATE notes SET endorsee_id=? WHERE id=?", (endorsee_id, note_id))
    return doc_id


def dishonor(conn, book, uid, note_id, action_date):
    n = _get(conn, book, note_id)
    if n["kind"] != "recv" or n["status"] != "held":
        raise ValueError("보유 중인 받을어음만 처리할 수 있습니다.")
    summary = f"{n['note_no']} 받을어음 부도"
    lines = [
        {"code": "246", "debit": n["amount"], "partner_id": n["partner_id"], "summary": summary},
        {"code": RECV_ACCT, "credit": n["amount"], "partner_id": n["partner_id"], "summary": summary},
    ]
    return _close(conn, book, uid, n, "dishonored", action_date, lines, summary)


def pay(conn, book, uid, note_id, action_date, bank_account_id):
    n = _get(conn, book, note_id)
    if n["kind"] != "pay" or n["status"] != "issued":
        raise ValueError("발행 중인 지급어음만 처리할 수 있습니다.")
    bank = _bank(conn, book, bank_account_id)
    summary = f"{n['note_no']} 지급어음 결제"
    lines = [
        {"code": PAY_ISSUE_ACCT, "debit": n["amount"], "partner_id": n["partner_id"], "summary": summary},
        {"code": bank["account_code"], "credit": n["amount"], "partner_id": bank["partner_id"], "summary": summary},
    ]
    return _close(conn, book, uid, n, "paid", action_date, lines, summary)


def cancel(conn, book, uid, note_id, rev_date=None):
    n = _get(conn, book, note_id)
    if n["status"] == "canceled":
        raise ValueError("이미 취소된 어음입니다.")
    base_status = "held" if n["kind"] == "recv" else "issued"
    if n["close_doc_id"]:
        doc_id, fallback_date, new_status = n["close_doc_id"], n["close_date"], base_status
    else:
        doc_id, fallback_date, new_status = n["issue_doc_id"], n["issue_date"], "canceled"
    rev = books.reverse(conn, doc_id, uid, rev_date or fallback_date)
    conn.execute(
        "UPDATE notes SET status=?, close_doc_id=NULL, close_date=NULL, endorsee_id=NULL WHERE id=?",
        (new_status, note_id),
    )
    audit.log(conn, uid, "note_cancel", "note", note_id, f"{n['note_no']} 처리취소", company_id=book)
    return rev

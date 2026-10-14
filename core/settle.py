from core import audit, books, credit
from core.tz import now_kst

ACCT = {"수금": "110", "지급": "251"}
# 금액이 미결 배분보다 크면 차액은 선수금/선급금. 충당 시에는 반대로 이 계정에서 차감
ADVANCE = {"수금": "257", "지급": "115"}
CASH = "101"
WHT_ACCOUNT = "253"
# 소득세율(%). 기타소득은 필요경비 60% 공제 후 20% 적용분. 지방소득세는 소득세의 10%
WHT_RATES = {"사업소득": 3, "기타소득": 8}


def calc_wht(wht_type, amount):
    rate = WHT_RATES.get(wht_type)
    if not rate:
        return 0, 0
    tax = amount * rate // 100 // 10 * 10
    return tax, tax // 10 // 10 * 10


def advance_balance(conn, book, kind, pid):
    dr, cr = conn.execute(
        """SELECT COALESCE(SUM(sl.debit),0), COALESCE(SUM(sl.credit),0)
           FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
           WHERE d.company_id=? AND d.status='done' AND sl.account_code=? AND sl.partner_id=?""",
        (book, ADVANCE[kind], pid)).fetchone()
    return cr - dr if kind == "수금" else dr - cr


def create(conn, book, uid, f):
    kind, pid, amount = f["kind"], f["partner_id"], f["amount"]
    p = conn.execute("SELECT name FROM partners WHERE id=? AND company_id=?", (pid, book)).fetchone()
    if not p:
        raise LookupError
    if amount <= 0:
        raise ValueError("금액을 입력해 주세요.")

    remain = {it["doc_id"]: it["remain"]
              for it in credit.open_items(conn, book, ACCT[kind], pid).get(pid, {"items": []})["items"]}
    items = [(cid, amt) for cid, amt in f["items"] if amt]
    for cid, amt in items:
        if cid not in remain:
            raise LookupError
        if amt < 0 or amt > remain[cid]:
            raise ValueError("미결 잔액을 초과하여 배분할 수 없습니다.")
    alloc = sum(amt for _, amt in items)
    rest = amount - alloc
    if rest < 0 or (rest and (f["method"] == "충당" or not f["advance"])):
        raise ValueError("배분 합계가 금액과 일치하지 않습니다.")

    wht_type = f["wht_type"] if kind == "지급" and f["method"] != "충당" else "없음"
    tax, local = calc_wht(wht_type, amount)

    bank_id = None
    if f["method"] == "보통예금":
        bank = conn.execute("SELECT id, account_code FROM bank_accounts WHERE id=? AND company_id=? AND is_active=1",
                            (f["bank_account_id"], book)).fetchone()
        if not bank:
            raise ValueError("계좌를 선택해 주세요.")
        cash, bank_id = bank["account_code"], bank["id"]
    elif f["method"] == "현금":
        cash = CASH
    elif f["method"] == "충당":
        cash = ADVANCE[kind]
        if amount > advance_balance(conn, book, kind, pid):
            raise ValueError(f"{'선수금' if kind == '수금' else '선급금'} 잔액이 부족합니다.")
    else:
        raise ValueError("결제 방법을 선택해 주세요.")

    summary = f"{p['name']} {kind}"
    cash_pid = pid if f["method"] == "충당" else None
    side = ("credit", "debit") if kind == "수금" else ("debit", "credit")
    lines = [{"code": cash, side[1]: amount - tax - local, "partner_id": cash_pid, "summary": summary}]
    if alloc:
        lines.append({"code": ACCT[kind], side[0]: alloc, "partner_id": pid, "summary": summary})
    if rest:
        lines.append({"code": ADVANCE[kind], side[0]: rest, "partner_id": pid, "summary": summary})
    for amt, label in ((tax, "소득세"), (local, "지방소득세")):
        if amt:
            lines.append({"code": WHT_ACCOUNT, "credit": amt, "summary": f"{p['name']} {wht_type} {label}"})

    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    sid = conn.execute(
        """INSERT INTO settlements (company_id, kind, settle_date, partner_id, amount, method, bank_account_id,
               account_code, wht_type, wht_amt, memo, created_by, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (book, kind, f["settle_date"], pid, amount, f["method"], bank_id, cash, wht_type, tax + local,
         f["memo"], uid, now)).lastrowid
    doc_id = books.post(conn, book, uid, f["settle_date"], lines, summary, "settlement", sid,
                        slip_type="입금" if kind == "수금" else "출금")
    conn.execute("UPDATE settlements SET doc_id=? WHERE id=?", (doc_id, sid))
    conn.executemany("INSERT INTO settlement_items (settlement_id, charge_doc_id, amount) VALUES (?,?,?)",
                     [(sid, cid, amt) for cid, amt in items])
    if f.get("bank_txn_id"):
        hit = conn.execute("UPDATE bank_txns SET status='처리', settlement_id=?, doc_id=? "
                           "WHERE id=? AND company_id=? AND status='미처리'",
                           (sid, doc_id, f["bank_txn_id"], book)).rowcount
        if not hit:
            raise ValueError("이미 처리된 은행 거래입니다.")
    audit.log(conn, uid, "settle_create", "settlement", sid, f"{summary} {amount:,}", company_id=book)
    return sid


def cancel(conn, book, uid, sid):
    s = conn.execute("SELECT * FROM settlements WHERE id=? AND company_id=?", (sid, book)).fetchone()
    if not s:
        raise LookupError
    if s["canceled_at"]:
        raise ValueError("이미 취소된 반제입니다.")
    rev = books.reverse(conn, s["doc_id"], uid, s["settle_date"])
    conn.execute("DELETE FROM settlement_items WHERE settlement_id=?", (sid,))
    conn.execute("UPDATE bank_txns SET status='미처리', settlement_id=NULL, doc_id=NULL WHERE settlement_id=?", (sid,))
    conn.execute("UPDATE settlements SET canceled_at=?, cancel_doc_id=? WHERE id=?",
                 (now_kst().strftime("%Y-%m-%d %H:%M:%S"), rev, sid))
    audit.log(conn, uid, "settle_cancel", "settlement", sid, f"{s['kind']} {s['amount']:,} 취소", company_id=book)

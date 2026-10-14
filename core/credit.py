from datetime import date, timedelta

MODES = {"off": "체크안함", "warn": "초과 시 경고", "block": "초과 시 저장불가"}

# 거래처 지정 없이 이름만 남은 과거 전표 포함
AR_WHERE = """FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
    WHERE d.company_id=? AND d.status='done' AND sl.account_code='110'
      AND (sl.partner_id=? OR (sl.partner_id IS NULL AND sl.partner=?))"""


def ar_balance(conn, book, p, until=None):
    sql = f"SELECT COALESCE(SUM(sl.debit),0) - COALESCE(SUM(sl.credit),0) {AR_WHERE}"
    args = [book, p["id"], p["name"]]
    if until:
        sql += " AND d.slip_date<=?"
        args.append(until)
    return conn.execute(sql, args).fetchone()[0]


def check(conn, book, partner_id, amount, on_date):
    co = conn.execute("SELECT credit_limit_mode, credit_days_mode FROM client_companies WHERE id=?",
                      (book,)).fetchone()
    p = conn.execute("SELECT id, name, credit_limit, credit_days FROM partners WHERE id=? AND company_id=?",
                     (partner_id, book)).fetchone()
    if not co or not p:
        return None
    msgs, block = [], False

    if co["credit_limit_mode"] != "off" and p["credit_limit"] > 0:
        bal = ar_balance(conn, book, p)
        over = bal + amount - p["credit_limit"]
        if over > 0:
            msgs.append(f"여신한도를 초과합니다.\n여신한도: {p['credit_limit']:,}원\n"
                        f"현재 미수잔액: {bal:,}원\n이번 입력금액: {amount:,}원\n초과금액: {over:,}원")
            block = co["credit_limit_mode"] == "block"

    # 기준일 이전 미수금을 이후 수금액으로 상계 후 남은 금액이 기간 초과분
    if co["credit_days_mode"] != "off" and p["credit_days"] > 0:
        cut = (date.fromisoformat(on_date) - timedelta(days=p["credit_days"])).isoformat()
        old = ar_balance(conn, book, p, cut)
        paid = conn.execute(f"SELECT COALESCE(SUM(sl.credit),0) {AR_WHERE} AND d.slip_date>?",
                            (book, p["id"], p["name"], cut)).fetchone()[0]
        short = old - paid
        if short > 0:
            day = cut.replace("-", ".")
            msgs.append(f"여신기간을 초과한 미수잔액이 있습니다.\n여신기간: {p['credit_days']}일\n"
                        f"{day}.까지의 미수금: {old:,}원\n{day}. ~ 현재까지의 수금액: {paid:,}원\n"
                        f"여신 부족 미수잔액: {short:,}원")
            block = block or co["credit_days_mode"] == "block"

    if not msgs:
        return None
    return {"msg": "\n\n".join(msgs), "block": block}


# 계정별 거래처 미결 항목. acct '110'(채권: 차변=청구, 대변=수금), '251'(채무: 대변=청구, 차변=지급)
# 청구 단위는 전표 문서. 반제 배분(settlement_items) 우선 차감, 반제 기록 없는 상계 라인은 오래된 순 배분
# 역분개 전표는 원 전표에 합산. 반제 전표와 그 취소 전표는 배분으로 반영되므로 집계 제외
# 이름만 남은 과거 라인은 같은 회사 내 동명 거래처로 매칭(AR_WHERE와 동일 기준)
# orphan=True면 매칭 거래처가 없는 과거 라인만 거래처명 기준으로 반환
def open_items(conn, book, acct, pid=None, orphan=False):
    charge_col, pay_col = ("debit", "credit") if acct == "110" else ("credit", "debit")
    where = """d.company_id=? AND d.status='done' AND sl.account_code=?
        AND COALESCE(d.reversal_of, d.id) NOT IN (SELECT doc_id FROM settlements WHERE company_id=? AND doc_id IS NOT NULL)"""
    args = [book, acct, book]
    if pid:
        where += """ AND (sl.partner_id=? OR (sl.partner_id IS NULL
                     AND sl.partner=(SELECT name FROM partners WHERE id=? AND company_id=?)))"""
        args += [pid, pid, book]

    if orphan:
        key, where = "sl.partner", where + " AND sl.partner_id IS NULL AND mp.id IS NULL AND sl.partner!=''"
    else:
        key = "COALESCE(sl.partner_id, mp.id)"
        where += f" AND {key} IS NOT NULL"

    rows = conn.execute(
        f"""SELECT {key} AS pid, COALESCE(d.reversal_of, d.id) AS doc_id, d.reversal_of AS rev,
                   d.slip_date, d.slip_no, d.title, sl.{charge_col} AS charge, sl.{pay_col} AS pay
            FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
            LEFT JOIN partners mp ON mp.company_id=d.company_id AND mp.name=sl.partner AND sl.partner_id IS NULL
            WHERE {where}
            ORDER BY pid, d.slip_date, d.id""",
        args,
    ).fetchall()

    settled = {} if orphan else {
        (r[0], r[1]): r[2] for r in conn.execute(
            """SELECT s.partner_id, si.charge_doc_id, SUM(si.amount) FROM settlement_items si
               JOIN settlements s ON s.id=si.settlement_id
               WHERE s.company_id=? AND s.kind=? GROUP BY s.partner_id, si.charge_doc_id""",
            (book, "수금" if acct == "110" else "지급"))
    }

    by_pid = {}
    for r in rows:
        docs = by_pid.setdefault(r["pid"], {})
        doc = docs.setdefault(r["doc_id"], {"net": 0})
        doc["net"] += (r["charge"] or 0) - (r["pay"] or 0)
        if not r["rev"]:
            doc.update(date=r["slip_date"], slip_no=r["slip_no"], title=r["title"])

    result = {}
    for p, docs in by_pid.items():
        items, legacy = [], 0
        for doc_id, doc in docs.items():
            if doc["net"] > 0:
                items.append({"doc_id": doc_id, "date": doc.get("date", ""), "slip_no": doc.get("slip_no", ""),
                              "title": doc.get("title", ""), "charge": doc["net"],
                              "remain": doc["net"] - settled.get((p, doc_id), 0)})
            elif doc["net"] < 0:
                legacy -= doc["net"]
        items.sort(key=lambda it: it["date"])
        for it in items:
            if legacy <= 0:
                break
            use = min(it["remain"], legacy)
            if use > 0:
                it["remain"] -= use
                legacy -= use
        result[p] = {"items": [it for it in items if it["remain"] > 0], "over": legacy}
    return result


from fastapi.responses import JSONResponse

from core import notification
from core.perms import level

DEFAULT_CFG = {"period": "year", "warn_pct": 90, "notify_pct": 95, "block_pct": 100}


def get_cfg(conn, book):
    row = conn.execute(
        "SELECT period, warn_pct, notify_pct, block_pct FROM budget_cfg WHERE company_id=?", (book,)
    ).fetchone()
    return dict(row) if row else dict(DEFAULT_CFG)


def save_cfg(conn, book, period, warn_pct, notify_pct, block_pct):
    conn.execute(
        """INSERT INTO budget_cfg (company_id, period, warn_pct, notify_pct, block_pct) VALUES (?,?,?,?,?)
           ON CONFLICT(company_id) DO UPDATE SET period=?, warn_pct=?, notify_pct=?, block_pct=?""",
        (book, period, warn_pct, notify_pct, block_pct, period, warn_pct, notify_pct, block_pct),
    )


def _is_expense(conn, book, code):
    row = conn.execute("SELECT category FROM accounts WHERE company_id=? AND code=?", (book, code)).fetchone()
    return bool(row) and row["category"] == "비용"


def _period_range(year, month, period):
    if period == "year":
        d_from = f"{year}-01-01"
    else:
        d_from = f"{year}-{month:02d}-01"
    d_to = f"{year+1}-01-01" if month == 12 else f"{year}-{month+1:02d}-01"
    return d_from, d_to


# 부서 예산이 없으면 전사 예산으로 대체. 둘 다 없으면 미편성(점검 제외)
def _budget_amt(conn, book, dept, code, year, month, period):
    months = list(range(1, 13)) if period == "year" else [month]
    qs = ",".join("?" * len(months))
    for d in ([dept, ""] if dept else [""]):
        row = conn.execute(
            f"SELECT COALESCE(SUM(amount),0) v FROM budgets "
            f"WHERE company_id=? AND dept=? AND account_code=? AND year=? AND month IN ({qs})",
            (book, d, code, year, *months),
        ).fetchone()
        if row["v"] > 0:
            return d, row["v"]
    return None, 0


def _actual_amt(conn, book, dept, code, year, month, period):
    d_from, d_to = _period_range(year, month, period)
    sql = """SELECT COALESCE(SUM(sl.debit) - SUM(sl.credit), 0) v FROM slip_lines sl
              JOIN erp_docs d ON sl.doc_id=d.id
              WHERE d.company_id=? AND d.status='done' AND sl.account_code=?
                AND d.slip_date>=? AND d.slip_date<?"""
    args = [book, code, d_from, d_to]
    if dept:
        sql += " AND COALESCE(sl.dept, '')=?"
        args.append(dept)
    return conn.execute(sql, args).fetchone()["v"]


def report(conn, book, dept, code, year, month, period):
    b_dept, bgt = _budget_amt(conn, book, dept, code, year, month, period)
    if bgt <= 0:
        return None
    act = _actual_amt(conn, book, b_dept, code, year, month, period)
    pct = round(act / bgt * 100) if bgt else 0
    return {
        "dept": b_dept, "code": code, "year": year, "month": month,
        "budget": bgt, "actual": act, "avail": bgt - act, "pct": pct,
    }


def usage(conn, book, dept, code, year, month, amount):
    if not _is_expense(conn, book, code):
        return None
    cfg = get_cfg(conn, book)
    r = report(conn, book, dept, code, year, month, cfg["period"])
    if not r:
        return None
    r["actual"] += amount
    r["avail"] -= amount
    r["pct"] = round(r["actual"] / r["budget"] * 100)
    r["cfg"] = cfg
    return r


# 전표 라인 중 부서+계정별로 모아 가용성 점검. 라인에 없는 dept 키는 ''(전사) 취급
def evaluate(conn, book, lines, slip_date):
    year, month = int(slip_date[:4]), int(slip_date[5:7])
    groups = {}
    for l in lines:
        amt = l.get("debit", 0)
        if not amt:
            continue
        key = (l.get("dept", "") or "", l["code"])
        groups[key] = groups.get(key, 0) + amt
    results = []
    for (dept, code), amt in groups.items():
        info = usage(conn, book, dept, code, year, month, amt)
        if info:
            results.append(info)
    return results


def worst_warning(infos):
    cands = [i for i in infos if i["pct"] >= i["cfg"]["warn_pct"]]
    if not cands:
        return None
    best = max(cands, key=lambda i: i["pct"])
    block_pct = best["cfg"]["block_pct"]
    best["block"] = bool(block_pct) and best["pct"] >= block_pct
    best["msg"] = f"[{best['code']}] 계정 예산 사용률 {best['pct']}%입니다."
    return best


# 여신 경고와 동일한 confirm/notice 응답 패턴. block이면 저장 차단, 아니면 확인 후 재전송
def reply(over):
    if over["block"]:
        return JSONResponse({"notice": over["msg"] + "\n\n예산을 초과하여 저장할 수 없습니다."}, status_code=400)
    return JSONResponse({"confirm": over["msg"] + "\n\n저장하시겠습니까?"}, status_code=409)


def _fi_users(conn, book):
    from core.books import book_users
    return [u["id"] for u in book_users(conn, book) if level(conn, u["id"], "fi") != "none"]


# 같은 부서+계정+연월 조합은 한 번만 알림. budget_notified에 기록해 중복 방지
def notify_crossings(conn, book, infos):
    for i in infos:
        if i["pct"] < i["cfg"]["notify_pct"]:
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO budget_notified (company_id, dept, account_code, year, month) VALUES (?,?,?,?,?)",
            (book, i["dept"], i["code"], i["year"], i["month"]),
        )
        if cur.rowcount == 0:
            continue
        uids = _fi_users(conn, book)
        if not uids:
            continue
        dept_label = i["dept"] or "전사"
        notification.create_bulk_notifications(
            conn, uids, "예산 사용률 경고",
            f"[{dept_label}] {i['code']} 계정 {i['year']}년 {i['month']}월 예산 사용률 {i['pct']}%",
            f"/budget/vs-actual?year={i['year']}&month={i['month']}&dept={i['dept']}",
        )


# 반환 가용액 산정용. 단일 월 기준(편성/추가/반환은 월별 행에 적용)
def available(conn, book, dept, code, year, month):
    row = conn.execute(
        "SELECT COALESCE(SUM(amount),0) v FROM budgets WHERE company_id=? AND dept=? AND account_code=? AND year=? AND month=?",
        (book, dept, code, year, month),
    ).fetchone()
    bgt = row["v"]
    act = _actual_amt(conn, book, dept, code, year, month, "month")
    return bgt - act


# budgets.amount는 이력 합계와 같게 유지. kind별로 증감 방향이 다름
def apply_change(conn, book, dept, code, year, month, kind, amount, reason, uid):
    delta = amount if kind in ("편성", "추가") else -amount
    conn.execute(
        """INSERT INTO budgets (company_id, dept, account_code, year, month, amount, created_by, created_at)
           VALUES (?,?,?,?,?,?,?,datetime('now','localtime'))
           ON CONFLICT(company_id, dept, account_code, year, month) DO UPDATE SET amount=amount+?, created_by=?""",
        (book, dept, code, year, month, delta, uid, delta, uid),
    )
    conn.execute(
        """INSERT INTO budget_changes (company_id, dept, account_code, year, month, kind, amount, reason, created_by)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (book, dept, code, year, month, kind, delta, reason, uid),
    )

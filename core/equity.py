from core import audit, books

RE_ACCOUNTS = ("341", "351", "356", "375", "377")


def acct_balance(conn, book, code, as_of):
    r = conn.execute(
        """SELECT a.is_debit, COALESCE(SUM(sl.debit),0) d, COALESCE(SUM(sl.credit),0) c
           FROM accounts a LEFT JOIN slip_lines sl ON sl.account_code = a.code
           LEFT JOIN erp_docs ed ON sl.doc_id = ed.id AND ed.company_id = ? AND ed.status = 'done'
                AND ed.slip_date <= ?
           WHERE a.company_id = ? AND a.code = ?
           GROUP BY a.is_debit""",
        (book, as_of, book, code),
    ).fetchone()
    if not r:
        return 0
    return r["d"] - r["c"] if r["is_debit"] else r["c"] - r["d"]


def net_change(conn, book, code, date_from, date_to):
    r = conn.execute(
        """SELECT COALESCE(SUM(sl.credit - sl.debit), 0) chg FROM slip_lines sl
           JOIN erp_docs ed ON sl.doc_id = ed.id
           WHERE sl.account_code = ? AND ed.company_id = ? AND ed.status = 'done'
                AND ed.slip_date BETWEEN ? AND ?""",
        (code, book, date_from, date_to),
    ).fetchone()
    return r["chg"] or 0


# 연차배당(처분 전표)으로 375 계정이 줄어든 금액. 자본변동표 행 계산용
def approp_amount(conn, book, date_from, date_to):
    r = conn.execute(
        """SELECT COALESCE(SUM(sl.debit), 0) amt FROM slip_lines sl
           JOIN erp_docs ed ON sl.doc_id = ed.id
           WHERE sl.account_code = '375' AND ed.source_type = 're_approp' AND ed.company_id = ?
                AND ed.status = 'done' AND ed.slip_date BETWEEN ? AND ?""",
        (book, date_from, date_to),
    ).fetchone()
    return r["amt"] or 0


# 이익준비금이 현금배당의 1/10 미만이면 경고(상법 458조). 누계가 자본금 1/2 이상이면 경고 생략
def reserve_warn(conn, book, year, legal_reserve, cash_div):
    if cash_div <= 0 or legal_reserve * 10 >= cash_div:
        return None
    as_of = f"{year}-12-31"
    capital = acct_balance(conn, book, "331", as_of)
    reserve_total = acct_balance(conn, book, "351", as_of) + legal_reserve
    if capital > 0 and reserve_total >= capital / 2:
        return None
    return "이익준비금이 현금배당의 1/10 미만입니다 (상법 458조)."


def get_approp(conn, book, year):
    return conn.execute(
        "SELECT * FROM re_appropriations WHERE company_id=? AND year=?", (book, year)
    ).fetchone()


# 처분 확정. 차 375 / 대 351, 265, 356
def approve(conn, book, uid, year, approve_date, legal_reserve, cash_div, other_reserve):
    if get_approp(conn, book, year):
        raise ValueError("이미 처분 확정된 연도입니다.")
    total = legal_reserve + cash_div + other_reserve
    if legal_reserve < 0 or cash_div < 0 or other_reserve < 0 or total <= 0:
        raise ValueError("처분액을 확인해 주세요.")

    rid = conn.execute(
        """INSERT INTO re_appropriations (company_id, year, approve_date, legal_reserve, cash_div, other_reserve,
               created_by, created_at) VALUES (?,?,?,?,?,?,?,datetime('now','localtime'))""",
        (book, year, approve_date, legal_reserve, cash_div, other_reserve, uid),
    ).lastrowid

    summary = f"{year}년 이익잉여금처분"
    lines = [{"code": "375", "debit": total, "summary": summary}]
    if legal_reserve:
        lines.append({"code": "351", "credit": legal_reserve, "summary": summary})
    if cash_div:
        lines.append({"code": "265", "credit": cash_div, "summary": summary})
    if other_reserve:
        lines.append({"code": "356", "credit": other_reserve, "summary": summary})
    doc_id = books.post(conn, book, uid, approve_date, lines, summary, "re_approp", rid)
    conn.execute("UPDATE re_appropriations SET doc_id=? WHERE id=?", (doc_id, rid))
    audit.log(conn, uid, "re_approp", "re_appropriation", rid, f"{summary} {total:,}", company_id=book)
    return rid


# 확정 취소. 처분 전표를 역분개하고 처분 기록 삭제(같은 연도 재확정 가능)
def cancel(conn, book, uid, year, rev_date):
    r = get_approp(conn, book, year)
    if not r:
        raise LookupError
    books.reverse(conn, r["doc_id"], uid, rev_date)
    conn.execute("DELETE FROM re_appropriations WHERE id=?", (r["id"],))
    audit.log(conn, uid, "re_approp_cancel", "re_appropriation", r["id"], f"{year}년 처분 확정 취소", company_id=book)

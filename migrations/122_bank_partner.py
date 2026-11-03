# 보통예금 계좌별 금융거래처 생성. 계좌가 1개뿐인 계정코드만 기존 확정 전표 일괄 보정


def up(conn):
    conn.execute("ALTER TABLE bank_accounts ADD COLUMN partner_id INTEGER REFERENCES partners(id)")

    seqs = {}
    for a in conn.execute("SELECT id, company_id, bank, name, is_active FROM bank_accounts").fetchall():
        book = a["company_id"]
        if book not in seqs:
            last = conn.execute(
                "SELECT code FROM partners WHERE company_id=? AND code GLOB '[0-9][0-9][0-9][0-9][0-9]' ORDER BY code DESC LIMIT 1",
                (book,),
            ).fetchone()
            seqs[book] = int(last["code"]) if last else 0
        seqs[book] += 1
        pid = conn.execute(
            "INSERT INTO partners (company_id, code, name, kind, partner_type, is_active, trade_status) VALUES (?,?,?,?,?,?,?)",
            (book, f"{seqs[book]:05d}", f"{a['bank']} {a['name']}", "finance", "both", a["is_active"],
             "active" if a["is_active"] else "stop"),
        ).lastrowid
        conn.execute("UPDATE bank_accounts SET partner_id=? WHERE id=?", (pid, a["id"]))

    # 계좌가 정확히 1개인 계정코드만 기존 확정 전표 보정 대상
    single = conn.execute("""
        SELECT company_id, account_code, MIN(partner_id) AS pid
        FROM bank_accounts GROUP BY company_id, account_code HAVING COUNT(*)=1
    """).fetchall()

    corrected = {}
    for row in single:
        book, code, pid = row["company_id"], row["account_code"], row["pid"]
        cnt = conn.execute(
            """SELECT COUNT(*) FROM slip_lines
               WHERE account_code=? AND doc_id IN (SELECT id FROM erp_docs WHERE company_id=? AND status='done')""",
            (code, book),
        ).fetchone()[0]
        if not cnt:
            continue
        pname = conn.execute("SELECT name FROM partners WHERE id=?", (pid,)).fetchone()["name"]
        conn.execute(
            """UPDATE slip_lines SET partner_id=?, partner=?
               WHERE account_code=? AND doc_id IN (SELECT id FROM erp_docs WHERE company_id=? AND status='done')""",
            (pid, pname, code, book),
        )
        corrected.setdefault(book, []).append(f"{code} {cnt}건")

    for book, parts in corrected.items():
        conn.execute(
            "INSERT INTO audit_logs (at, action, company_id, target_type, summary) VALUES (datetime('now','localtime'),'migrate',?,?,?)",
            (book, "slip_lines", ", ".join(parts)),
        )

    conn.commit()

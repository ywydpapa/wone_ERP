from core import books


def calc_vat(supply):
    return int(supply / 10)


def split_total(total):
    supply = total * 10 // 11
    return supply, total - supply


def terms(conn, partner_id, supply):
    row = conn.execute("SELECT tax_type FROM partners WHERE id=?", (partner_id,)).fetchone() if partner_id else None
    tax_type = row["tax_type"] if row and row["tax_type"] else "과세"
    evidence = "계산서" if tax_type == "면세" else "세금계산서"
    return tax_type, evidence, calc_vat(supply) if tax_type == "과세" else 0


def inv_lines(inv, acct, pay, summary):
    supply, vat = inv["supply_amt"], inv["vat"]
    if inv["kind"] == "매출":
        rows = [(pay, supply + vat, 0), (acct, 0, supply), ("255", 0, vat)]
    elif inv["deduct"]:
        rows = [(acct, supply, 0), ("135", vat, 0), (pay, 0, supply + vat)]
    else:
        rows = [(acct, supply + vat, 0), (pay, 0, supply + vat)]
    lines = []
    for code, d, c in rows:
        # 음수면 차대 뒤집음
        if d < 0 or c < 0:
            d, c = -c, -d
        if d or c:
            lines.append({"code": code, "debit": d, "credit": c, "partner_id": inv["partner_id"], "summary": summary})
    return lines


def add(conn, book, uid, inv, items=()):
    inv_id = conn.execute(
        """INSERT INTO tax_invoices (company_id, kind, tax_type, evidence, issue_date, partner_id, supply_amt, vat,
               total, approval_no, is_electronic, deduct, doc_id, source_type, source_id, status, orig_id, created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (book, inv["kind"], inv["tax_type"], inv["evidence"], inv["issue_date"], inv["partner_id"],
         inv["supply_amt"], inv["vat"], inv["supply_amt"] + inv["vat"], inv.get("approval_no", ""),
         inv.get("is_electronic", 1), inv.get("deduct", 1), inv["doc_id"], inv.get("source_type", "manual"),
         inv.get("source_id"), inv.get("status", "정상"), inv.get("orig_id"), uid),
    ).lastrowid
    # 품목별 세액 절사 차이는 마지막 줄에서 맞춤
    left = inv["vat"]
    for no, it in enumerate(items, 1):
        vat = 0
        if inv["vat"]:
            vat = left if no == len(items) else calc_vat(it["supply_amt"])
        left -= vat
        conn.execute(
            """INSERT INTO tax_invoice_items (invoice_id, line_no, item_date, name, spec, qty, unit_price, supply_amt, vat)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (inv_id, no, it.get("item_date") or inv["issue_date"], it["name"], it.get("spec", ""),
             it.get("qty", 0), it.get("unit_price", 0), it["supply_amt"], vat),
        )
    return inv_id


def vat_return(conn, book, d_from, d_to):
    rows = conn.execute(
        """SELECT kind, tax_type, evidence, deduct, COUNT(*) AS cnt, SUM(supply_amt) AS supply, SUM(vat) AS vat
           FROM tax_invoices WHERE company_id=? AND issue_date BETWEEN ? AND ?
           GROUP BY kind, tax_type, evidence, deduct""",
        (book, d_from, d_to),
    ).fetchall()

    def pick(kind, cond):
        hit = [r for r in rows if r["kind"] == kind and cond(r)]
        return sum(r["cnt"] for r in hit), sum(r["supply"] for r in hit), sum(r["vat"] for r in hit)

    card = ("카드", "현금영수증")
    sales = [
        ("과세 세금계산서 발급분", *pick("매출", lambda r: r["tax_type"] == "과세" and r["evidence"] == "세금계산서")),
        ("과세 카드/현금영수증 발행분", *pick("매출", lambda r: r["tax_type"] == "과세" and r["evidence"] in card)),
        ("영세율 세금계산서 발급분", *pick("매출", lambda r: r["tax_type"] == "영세" and r["evidence"] == "세금계산서")),
        ("영세율 기타", *pick("매출", lambda r: r["tax_type"] == "영세" and r["evidence"] in card)),
    ]
    tax_inv = pick("매입", lambda r: r["evidence"] == "세금계산서")
    card_in = pick("매입", lambda r: r["evidence"] in card and r["deduct"])
    nondeduct = pick("매입", lambda r: r["evidence"] == "세금계산서" and not r["deduct"])
    buy_vat = tax_inv[2] + card_in[2] - nondeduct[2]
    buys = [
        ("세금계산서 수취분", *tax_inv),
        ("신용카드/현금영수증 수취분", *card_in),
        # 불공제는 차감 표시라 음수
        ("공제받지 못할 매입세액", nondeduct[0], nondeduct[1], -nondeduct[2]),
    ]
    exempt = [
        ("면세 계산서 발급분", *pick("매출", lambda r: r["evidence"] == "계산서")),
        ("계산서 수취분", *pick("매입", lambda r: r["evidence"] == "계산서")),
    ]
    sales_vat = sum(r[3] for r in sales)

    bal = conn.execute(
        """SELECT COALESCE(SUM(CASE WHEN sl.account_code='255' THEN sl.credit - sl.debit END), 0),
                  COALESCE(SUM(CASE WHEN sl.account_code='135' THEN sl.debit - sl.credit END), 0)
           FROM slip_lines sl JOIN erp_docs d ON d.id=sl.doc_id
           WHERE d.company_id=? AND d.status='done' AND d.slip_date BETWEEN ? AND ?""",
        (book, d_from, d_to),
    ).fetchone()
    warns = []
    if bal[0] != sales_vat:
        warns.append(f"부가세예수금(255) 장부 {bal[0]:,}원과 매출세액 {sales_vat:,}원이 다릅니다.")
    if bal[1] != buy_vat:
        warns.append(f"부가세대급금(135) 장부 {bal[1]:,}원과 공제 매입세액 {buy_vat:,}원이 다릅니다.")
    return {"sales": sales, "buys": buys, "exempt": exempt, "sales_vat": sales_vat, "buy_vat": buy_vat,
            "payable": sales_vat - buy_vat, "book_255": bal[0], "book_135": bal[1], "warns": warns}


def partner_totals(conn, book, kind, d_from, d_to):
    rows = [dict(r) for r in conn.execute(
        """SELECT p.name AS partner_name, p.biz_no, t.is_electronic, COUNT(*) AS cnt,
                  SUM(t.supply_amt) AS supply, SUM(t.vat) AS vat
           FROM tax_invoices t JOIN partners p ON p.id=t.partner_id
           WHERE t.company_id=? AND t.kind=? AND t.evidence='세금계산서' AND t.issue_date BETWEEN ? AND ?
           GROUP BY t.partner_id, t.is_electronic
           ORDER BY t.is_electronic DESC, supply DESC""",
        (book, kind, d_from, d_to),
    )]
    totals = {}
    for e in (1, 0):
        hit = [r for r in rows if r["is_electronic"] == e]
        totals[e] = (sum(r["cnt"] for r in hit), sum(r["supply"] for r in hit), sum(r["vat"] for r in hit))
    return rows, totals


def amend(conn, book, uid, orig_id, issue_date, supply):
    orig = conn.execute("SELECT * FROM tax_invoices WHERE id=? AND company_id=?", (orig_id, book)).fetchone()
    if not orig or orig["status"] != "정상":
        raise ValueError("수정할 수 없는 세금계산서입니다.")
    if orig["evidence"] not in ("세금계산서", "계산서"):
        raise ValueError("카드/현금영수증은 수정발행 대상이 아닙니다.")
    cur = conn.execute(
        "SELECT SUM(supply_amt), SUM(vat) FROM tax_invoices WHERE id=? OR orig_id=?", (orig_id, orig_id)
    ).fetchone()
    if cur[0] == 0 and cur[1] == 0:
        raise ValueError("이미 취소된 세금계산서입니다.")
    new_vat = calc_vat(supply) if orig["tax_type"] == "과세" else 0
    d_supply, d_vat = supply - cur[0], new_vat - cur[1]
    if not d_supply and not d_vat:
        raise ValueError("변경된 금액이 없습니다.")
    # 원본 전표의 계정을 그대로 사용
    lines = conn.execute("SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=?", (orig["doc_id"],)).fetchall()
    if orig["kind"] == "매출":
        pay = next(l["account_code"] for l in lines if l["debit"])
        acct = next(l["account_code"] for l in lines if l["credit"] and l["account_code"] != "255")
    else:
        pay = next(l["account_code"] for l in lines if l["credit"])
        acct = next(l["account_code"] for l in lines if l["debit"] and l["account_code"] != "135")
    status = "취소" if supply == 0 else "수정"
    inv = {**dict(orig), "issue_date": issue_date, "supply_amt": d_supply, "vat": d_vat, "status": status,
           "orig_id": orig_id, "approval_no": "", "source_type": "amend", "source_id": orig_id}
    name = conn.execute("SELECT name FROM partners WHERE id=?", (orig["partner_id"],)).fetchone()["name"]
    doc_id = books.post(conn, book, uid, issue_date, inv_lines(inv, acct, pay, f"{status} {orig['kind']} {name}"),
                        f"[{status}] {orig['kind']} {orig['evidence']} ({name})", "tax", None)
    inv_id = add(conn, book, uid, {**inv, "doc_id": doc_id})
    conn.execute("UPDATE erp_docs SET source_id=? WHERE id=?", (inv_id, doc_id))
    return inv_id

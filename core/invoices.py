from datetime import date, timedelta

from core import books
from core.assets import ACCUM

AMEND_REASONS = {
    1: "기재사항 착오정정",
    2: "공급가액 변동",
    3: "환입",
    4: "계약의 해제",
    5: "내국신용장 사후개설",
    6: "착오에 의한 이중발급",
}
# 원래 작성일자 유지 / 전체 취소 사유
FIX_DATE = (1, 5, 6)
FULL_CANCEL = (4, 6)

# 매입세액불공제내역 서식 기준 사유 코드
NONDEDUCT_REASONS = {
    1: "필요적 기재사항 누락 등",
    2: "사업과 직접 관련 없는 지출",
    3: "비영업용 소형승용자동차 구입/유지/임차",
    4: "접대비 및 이와 유사한 비용 관련",
    5: "면세사업 등 관련",
    6: "토지의 자본적 지출 관련",
    7: "사업자등록 전 매입세액",
    8: "금거래계좌 미사용 관련 매입세액",
}
# 신고서 고정자산매입 구분용 유형자산 계정
FIXED_CODES = tuple(ACCUM)


def calc_vat(supply):
    return int(supply / 10)


def terms(conn, partner_id, supply):
    row = conn.execute("SELECT tax_type FROM partners WHERE id=?", (partner_id,)).fetchone() if partner_id else None
    tax_type = row["tax_type"] if row and row["tax_type"] else "과세"
    evidence = "계산서" if tax_type == "면세" else "세금계산서"
    return tax_type, evidence, calc_vat(supply) if tax_type == "과세" else 0


def inv_lines(inv, acct, pay, summary, pay_pid=None):
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
        if not (d or c):
            continue
        # 결제 줄은 계좌면 금융거래처, 현금은 거래처 없음. 그 외 줄은 상대 거래처
        if code == pay:
            pid = pay_pid if pay_pid else (None if pay == "101" else inv["partner_id"])
        else:
            pid = inv["partner_id"]
        lines.append({"code": code, "debit": d, "credit": c, "partner_id": pid, "summary": summary})
    return lines


# 불공제 부가세 차액은 첫 줄에 합산
def split_acct(lines, acct, splits):
    row = next((l for l in lines if l["code"] == acct), None)
    if not row or not splits:
        return lines
    side, other = ("debit", "credit") if row["debit"] else ("credit", "debit")
    grouped = {}
    for s in splits:
        key = (s["code"], s.get("dept", ""), s.get("project_code", ""))
        grouped[key] = grouped.get(key, 0) + s["amount"]
    rest = row[side] - sum(grouped.values())
    lines.remove(row)
    for i, ((code, dept, proj), amt) in enumerate(grouped.items()):
        lines.append({**row, "code": code, side: amt + (rest if i == 0 else 0), other: 0,
                      "dept": dept, "project_code": proj})
    return lines


def add(conn, book, uid, inv, items=()):
    inv_id = conn.execute(
        """INSERT INTO tax_invoices (company_id, kind, tax_type, evidence, issue_date, partner_id, supply_amt, vat,
               total, approval_no, is_electronic, deduct, doc_id, source_type, source_id, status, orig_id, created_by,
               receipt_type, remark, amend_reason, lc_no, lc_open_date, nondeduct_reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (book, inv["kind"], inv["tax_type"], inv["evidence"], inv["issue_date"], inv["partner_id"],
         inv["supply_amt"], inv["vat"], inv["supply_amt"] + inv["vat"], inv.get("approval_no", ""),
         inv.get("is_electronic", 1), inv.get("deduct", 1), inv["doc_id"], inv.get("source_type", "manual"),
         inv.get("source_id"), inv.get("status", "정상"), inv.get("orig_id"), uid,
         inv.get("receipt_type") or "청구", inv.get("remark") or "", inv.get("amend_reason"),
         inv.get("lc_no") or "", inv.get("lc_open_date"), inv.get("nondeduct_reason")),
    ).lastrowid
    # 품목별 세액 절사 차이는 마지막 줄에서 보정, 직접 입력한 세액은 유지
    left = inv["vat"]
    for no, it in enumerate(items, 1):
        vat = 0
        if "vat" in it:
            vat = it["vat"]
        elif inv["vat"]:
            vat = left if no == len(items) else calc_vat(it["supply_amt"])
        left -= vat
        conn.execute(
            """INSERT INTO tax_invoice_items (invoice_id, line_no, item_date, name, spec, qty, unit_price, supply_amt, vat, note)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (inv_id, no, it.get("item_date") or inv["issue_date"], it["name"], it.get("spec", ""),
             it.get("qty", 0), it.get("unit_price", 0), it["supply_amt"], vat, it.get("note", "")),
        )
    return inv_id


EVIDENCES = ("세금계산서", "계산서", "카드", "현금영수증", "기타")

# 더존 매입매출전표 유형 코드. 값은 (약칭, 구분, 과세유형, 증빙, 공제)
VAT_TYPES = {
    "11": ("과세", "매출", "과세", "세금계산서", 1),
    "12": ("영세", "매출", "영세", "세금계산서", 1),
    "13": ("면세", "매출", "면세", "계산서", 1),
    "14": ("건별", "매출", "과세", "기타", 1),
    "16": ("수출", "매출", "영세", "기타", 1),
    "17": ("카과", "매출", "과세", "카드", 1),
    "18": ("카면", "매출", "면세", "카드", 1),
    "19": ("카영", "매출", "영세", "카드", 1),
    "22": ("현과", "매출", "과세", "현금영수증", 1),
    "23": ("현면", "매출", "면세", "현금영수증", 1),
    "24": ("현영", "매출", "영세", "현금영수증", 1),
    "51": ("과세", "매입", "과세", "세금계산서", 1),
    "52": ("영세", "매입", "영세", "세금계산서", 1),
    "53": ("면세", "매입", "면세", "계산서", 1),
    "54": ("불공", "매입", "과세", "세금계산서", 0),
    "57": ("카과", "매입", "과세", "카드", 1),
    "58": ("카면", "매입", "면세", "카드", 1),
    "59": ("카영", "매입", "영세", "카드", 1),
    "61": ("현과", "매입", "과세", "현금영수증", 1),
    "62": ("현면", "매입", "면세", "현금영수증", 1),
}
_CODE_OF = {v[1:]: k for k, v in VAT_TYPES.items()}


# 카드/현금영수증 불공제 매입은 더존 기준 일반전표 처리 대상. 코드 없음
def vat_code(r):
    deduct = 1 if r["kind"] == "매출" else int(bool(r["deduct"]))
    code = _CODE_OF.get((r["kind"], r["tax_type"], r["evidence"], deduct), "")
    return f"{code} {VAT_TYPES[code][0]}" if code else ""


def vat_return(conn, book, d_from, d_to):
    q = ",".join("?" * len(FIXED_CODES))
    rows = conn.execute(
        f"""SELECT kind, tax_type, evidence, deduct, COUNT(*) AS cnt, SUM(supply_amt) AS supply, SUM(vat) AS vat,
                   EXISTS(SELECT 1 FROM slip_lines sl WHERE sl.doc_id=t.doc_id AND sl.account_code IN ({q})) AS fixed
            FROM tax_invoices t WHERE company_id=? AND issue_date BETWEEN ? AND ?
            GROUP BY kind, tax_type, evidence, deduct, fixed""",
        (*FIXED_CODES, book, d_from, d_to),
    ).fetchall()

    def pick(kind, cond):
        hit = [r for r in rows if r["kind"] == kind and cond(r)]
        return sum(r["cnt"] for r in hit), sum(r["supply"] for r in hit), sum(r["vat"] for r in hit)

    card = ("카드", "현금영수증")
    sales = [
        ("과세 세금계산서 발급분", *pick("매출", lambda r: r["tax_type"] == "과세" and r["evidence"] == "세금계산서")),
        ("과세 카드/현금영수증 발행분", *pick("매출", lambda r: r["tax_type"] == "과세" and r["evidence"] in card)),
        ("과세 기타(정규영수증 외 매출분)", *pick("매출", lambda r: r["tax_type"] == "과세" and r["evidence"] == "기타")),
        ("영세율 세금계산서 발급분", *pick("매출", lambda r: r["tax_type"] == "영세" and r["evidence"] == "세금계산서")),
        ("영세율 기타", *pick("매출", lambda r: r["tax_type"] == "영세" and r["evidence"] != "세금계산서")),
    ]
    tax_gen = pick("매입", lambda r: r["evidence"] == "세금계산서" and not r["fixed"])
    tax_fix = pick("매입", lambda r: r["evidence"] == "세금계산서" and r["fixed"])
    card_gen = pick("매입", lambda r: r["evidence"] in card and r["deduct"] and not r["fixed"])
    card_fix = pick("매입", lambda r: r["evidence"] in card and r["deduct"] and r["fixed"])
    nondeduct = pick("매입", lambda r: r["evidence"] == "세금계산서" and not r["deduct"])
    buy_vat = tax_gen[2] + tax_fix[2] + card_gen[2] + card_fix[2] - nondeduct[2]
    buys = [
        ("세금계산서 수취분 일반매입", *tax_gen),
        ("세금계산서 수취분 고정자산매입", *tax_fix),
        ("신용카드/현금영수증 수취분 일반매입", *card_gen),
        ("신용카드/현금영수증 수취분 고정자산매입", *card_fix),
        # 불공제는 차감 표시라 음수
        ("공제받지 못할 매입세액", nondeduct[0], nondeduct[1], -nondeduct[2]),
    ]
    exempt = [
        ("면세 수입금액", *pick("매출", lambda r: r["tax_type"] == "면세")),
        ("계산서 발급금액", *pick("매출", lambda r: r["evidence"] == "계산서")),
        ("계산서 수취금액", *pick("매입", lambda r: r["evidence"] == "계산서")),
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
        """SELECT p.id AS partner_id, p.name AS partner_name, p.biz_no, p.representative, p.biz_type,
                  t.is_electronic, COUNT(*) AS cnt, SUM(t.supply_amt) AS supply, SUM(t.vat) AS vat
           FROM tax_invoices t JOIN partners p ON p.id=t.partner_id
           WHERE t.company_id=? AND t.kind=? AND t.evidence='세금계산서' AND t.issue_date BETWEEN ? AND ?
           GROUP BY t.partner_id, t.is_electronic
           ORDER BY t.is_electronic DESC, supply DESC""",
        (book, kind, d_from, d_to),
    )]
    for r in rows:
        r["reg_type"] = reg_type(r["biz_no"])
    totals = {}
    for e in (1, 0):
        hit = [r for r in rows if r["is_electronic"] == e]
        totals[e] = (sum(r["cnt"] for r in hit), sum(r["supply"] for r in hit), sum(r["vat"] for r in hit))
    return rows, totals


# 사업자등록번호(10자리) / 주민등록번호(13자리) 구분. 그 외는 사업자로 취급
def reg_type(biz_no):
    digits = "".join(c for c in (biz_no or "") if c.isdigit())
    return "주민" if len(digits) == 13 else "사업자"


def summary_breakdown(rows):
    def agg(items):
        return {"partners": len(items), "cnt": sum(r["cnt"] for r in items),
                "supply": sum(r["supply"] for r in items), "vat": sum(r["vat"] for r in items)}

    result = {}
    for e in (1, 0):
        hit = [r for r in rows if r["is_electronic"] == e]
        biz = [r for r in hit if r["reg_type"] == "사업자"]
        resident = [r for r in hit if r["reg_type"] == "주민"]
        result[e] = {"사업자": agg(biz), "주민": agg(resident), "소계": agg(hit)}
    result["합계"] = {k: result[1]["소계"][k] + result[0]["소계"][k] for k in ("partners", "cnt", "supply", "vat")}
    return result


def nondeduct_summary(conn, book, d_from, d_to):
    rows = conn.execute(
        """SELECT nondeduct_reason, COUNT(*) AS cnt, SUM(supply_amt) AS supply, SUM(vat) AS vat
           FROM tax_invoices WHERE company_id=? AND kind='매입' AND deduct=0 AND issue_date BETWEEN ? AND ?
           GROUP BY nondeduct_reason""",
        (book, d_from, d_to),
    ).fetchall()
    by_reason = {r["nondeduct_reason"]: r for r in rows}
    items = []
    for code, label in NONDEDUCT_REASONS.items():
        r = by_reason.get(code)
        items.append((code, label, r["cnt"] if r else 0, r["supply"] if r else 0, r["vat"] if r else 0))
    none_r = by_reason.get(None)
    unspec = (none_r["cnt"], none_r["supply"], none_r["vat"]) if none_r else (0, 0, 0)
    total = {"cnt": sum(i[2] for i in items) + unspec[0],
             "supply": sum(i[3] for i in items) + unspec[1],
             "vat": sum(i[4] for i in items) + unspec[2]}
    return {"rows": items, "unspec": unspec, "total": total}


# 당초 작성일자가 속한 과세기간(1~6월/7~12월) 종료일 + 25일
def lc_deadline(orig_issue_date):
    y, m = int(orig_issue_date[:4]), int(orig_issue_date[5:7])
    end = date(y, 6, 30) if m <= 6 else date(y, 12, 31)
    return end + timedelta(days=25)


def amend(conn, book, uid, orig_id, issue_date, supply, reason, lc_no="", lc_open_date=None):
    if reason not in AMEND_REASONS:
        raise ValueError("수정사유를 선택해 주세요.")
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

    # 착오정정/내국신용장/이중발급은 원래 작성일자를 그대로 사용
    if reason in FIX_DATE:
        issue_date = orig["issue_date"]
    # 계약해제/이중발급은 전체 취소
    if reason in FULL_CANCEL:
        supply = 0
    if reason == 3 and supply >= cur[0]:
        raise ValueError("환입은 공급가액이 줄어야 합니다.")
    if reason == 5:
        if orig["tax_type"] != "과세":
            raise ValueError("내국신용장 사후개설은 과세 세금계산서만 가능합니다.")
        if not lc_no or not lc_open_date:
            raise ValueError("신용장(구매확인서) 번호와 개설일을 입력해 주세요.")
        try:
            open_d = date.fromisoformat(lc_open_date)
        except ValueError:
            raise ValueError("개설일 형식이 잘못되었습니다.")
        deadline = lc_deadline(orig["issue_date"])
        if open_d > deadline:
            raise ValueError(f"내국신용장 개설 기한({deadline.isoformat()})이 지났습니다.")

    new_vat = calc_vat(supply) if orig["tax_type"] == "과세" else 0
    d_supply, d_vat = supply - cur[0], new_vat - cur[1]
    if reason != 5 and not d_supply and not d_vat:
        raise ValueError("변경된 금액이 없습니다.")
    # 원본 전표의 계정을 그대로 사용
    lines = conn.execute(
        """SELECT sl.account_code, sl.debit, sl.credit, p.id AS pid, p.kind FROM slip_lines sl
           LEFT JOIN partners p ON p.id=sl.partner_id WHERE sl.doc_id=?""", (orig["doc_id"],)
    ).fetchall()
    if orig["kind"] == "매출":
        pl = next(l for l in lines if l["debit"])
        acct = next(l["account_code"] for l in lines if l["credit"] and l["account_code"] != "255")
    else:
        pl = next(l for l in lines if l["credit"])
        acct = next(l["account_code"] for l in lines if l["debit"] and l["account_code"] != "135")
    pay = pl["account_code"]
    pay_pid = pl["pid"] if pl["kind"] == "finance" else None
    name = conn.execute("SELECT name FROM partners WHERE id=?", (orig["partner_id"],)).fetchone()["name"]
    inv = {**dict(orig), "issue_date": issue_date, "orig_id": orig_id, "approval_no": "", "source_type": "amend",
           "source_id": orig_id, "amend_reason": reason}
    # 내국신용장 사후개설은 당초 과세분 전액 (-) 발급 후 영세율 (+) 별도 발급. 이후 수정발행은 영세율분 기준
    if reason == 5:
        lc_remark = f"내국신용장 개설일 {lc_open_date} 번호 {lc_no}"
        _issue(conn, book, uid, {**inv, "supply_amt": -cur[0], "vat": -cur[1], "status": "취소",
                                  "lc_no": lc_no, "lc_open_date": lc_open_date}, acct, pay, pay_pid, name, "취소")
        zero = {**inv, "tax_type": "영세", "supply_amt": cur[0], "vat": 0, "status": "정상", "orig_id": None,
                "lc_no": lc_no, "lc_open_date": lc_open_date, "remark": lc_remark}
        return _issue(conn, book, uid, zero, acct, pay, pay_pid, name, "수정")
    status = "취소" if supply == 0 else "수정"
    return _issue(conn, book, uid, {**inv, "supply_amt": d_supply, "vat": d_vat, "status": status},
                  acct, pay, pay_pid, name, status)


def _issue(conn, book, uid, inv, acct, pay, pay_pid, name, label):
    doc_id = books.post(conn, book, uid, inv["issue_date"], inv_lines(inv, acct, pay, f"{label} {inv['kind']} {name}", pay_pid),
                        f"[{label}] {inv['kind']} {inv['evidence']} ({name})", "tax", None)
    inv_id = add(conn, book, uid, {**inv, "doc_id": doc_id})
    conn.execute("UPDATE erp_docs SET source_id=? WHERE id=?", (inv_id, doc_id))
    return inv_id

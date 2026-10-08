import argparse
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.db as dbmod
from core import books, invoices
from core.tz import now_kst
from routers._helpers import insert_approval_lines

START = "2026-07-01"
END = "2026-09-30"
YEAR = 2026

# (name, 대표자, 업태, 종목, 주소, 거래유형)
PARTNERS = [
    ("대명전자(주)", "김태호", "도소매업", "전자부품 유통", "경기도 부천시 오정구 산업로 123", "customer"),
    ("성진일렉트로닉스", "이정민", "제조업", "전자기기 조립", "서울특별시 구로구 디지털로 45", "customer"),
    ("우진테크놀로지(주)", "박선영", "제조업", "산업용 전자장비", "경기도 안산시 단원구 산단로 210", "customer"),
    ("한국하네스공업(주)", "최재원", "제조업", "케이블 하네스", "경기도 시흥시 정왕대로 88", "both"),
    ("삼정전자부품", "정민석", "도소매업", "전자부품 도매", "경기도 화성시 동탄산단로 17", "supplier"),
    ("동아정밀산업(주)", "강수현", "제조업", "정밀금속가공", "인천광역시 남동구 남동공단로 55", "supplier"),
    ("케이피이전자(주)", "윤지훈", "제조업", "전자제어장치", "서울특별시 금천구 가산디지털로 9", "customer"),
    ("서진산업", "조은비", "도소매업", "산업자재 유통", "경기도 김포시 통진산단로 31", "supplier"),
    ("태양전장(주)", "임현수", "제조업", "차량용 전장부품", "경기도 평택시 청북산단로 62", "customer"),
    ("대한커넥터공업", "한도윤", "제조업", "커넥터 제조", "경기도 수원시 권선구 산업로 14", "supplier"),
    ("신흥전자소재", "오세훈", "도소매업", "전자소재 유통", "서울특별시 성동구 성수이로 77", "supplier"),
    ("미래산업전자(주)", "문지은", "제조업", "산업용 제어기기", "경기도 성남시 중원구 성남대로 200", "customer"),
    ("대건테크", "배상철", "제조업", "정밀부품 가공", "경기도 군포시 공단로 9", "supplier"),
    ("원일전자(주)", "신유진", "도소매업", "전자부품 도소매", "서울특별시 영등포구 문래로 33", "both"),
    ("청우산업", "권오빈", "제조업", "전자조립 임가공", "경기도 광명시 소하로 21", "customer"),
    ("한별전자부품", "장미래", "도소매업", "전자부품 유통", "경기도 부천시 소사구 경인로 150", "supplier"),
    ("경인전선(주)", "나건우", "제조업", "전선 및 케이블", "인천광역시 부평구 부평대로 44", "both"),
    ("삼우전자공업", "구자영", "제조업", "전자기기 제조", "경기도 안양시 동안구 시민대로 88", "customer"),
    ("대신하네스", "홍성민", "제조업", "케이블 하네스", "경기도 오산시 산업로 6", "supplier"),
    ("유신전자산업", "백승호", "도소매업", "전자부품 유통", "서울특별시 강서구 마곡중앙로 12", "both"),
]

# (코드, 품명, 유형, 단위, 기준단가, 최소수량, 최대수량) - 수량은 도매 단위 기준
ITEMS = [
    ("ITM-006", "커넥터 4핀", "material", "EA", 850, 2000, 20000),
    ("ITM-007", "커넥터 8핀", "material", "EA", 1450, 1400, 14000),
    ("ITM-008", "PCB기판 2층", "material", "EA", 3200, 700, 8000),
    ("ITM-009", "PCB기판 4층", "material", "EA", 6800, 350, 4000),
    ("ITM-010", "케이블 하네스 A형", "product", "EA", 4200, 550, 6000),
    ("ITM-011", "케이블 하네스 B형", "product", "EA", 5600, 400, 4500),
    ("ITM-012", "릴레이 스위치", "material", "EA", 2100, 700, 10000),
    ("ITM-013", "저항기 세트", "consumable", "BOX", 15000, 70, 800),
    ("ITM-014", "알루미늄 방열판", "material", "EA", 3800, 550, 5500),
    ("ITM-015", "전원 어댑터 모듈", "product", "EA", 12000, 200, 2200),
]

PURCHASE_CODES = {"ITM-006", "ITM-007", "ITM-008", "ITM-009", "ITM-012", "ITM-013", "ITM-014"}
CARD_ACCTS = ["804", "811", "812", "820", "821", "835", "833", "834"]


def calc_biz_no(seq):
    base = f"{130 + seq:03d}81{1000 + seq:04d}"
    d = [int(c) for c in base]
    w = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    s = sum(a * b for a, b in zip(d, w)) + (d[8] * 5) // 10
    chk = (10 - s % 10) % 10
    return f"{base[0:3]}-{base[3:5]}-{base[5:9]}{chk}"


def biz_days(d_from, d_to):
    cur = date.fromisoformat(d_from)
    end = date.fromisoformat(d_to)
    out = []
    while cur <= end:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def add_days(d, n):
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def uneven(rng, lo, hi):
    base = rng.randint(lo, hi)
    return base - base % 100 + rng.choice([0, 100, 200, 300, 500, 700, 800])


def pick_users(conn, book):
    clients = [r[0] for r in conn.execute("SELECT user_id FROM client_users WHERE company_id=?", (book,)).fetchall()]
    workers = [r[0] for r in conn.execute("SELECT user_id FROM employees WHERE company_id=?", (book,)).fetchall()]
    staff = conn.execute("SELECT id FROM users WHERE role='platform_staff' ORDER BY id LIMIT 1").fetchone()[0]
    pool = workers + clients
    approver = clients[0] if clients else (workers[0] if workers else staff)
    drafter = pool[0] if pool else approver
    reviewer = pool[1] if len(pool) > 1 else approver
    return drafter, reviewer, approver


def clear_seed(conn, book):
    old_pids = [r[0] for r in conn.execute(
        "SELECT id FROM partners WHERE company_id=? AND code LIKE 'S%'", (book,)).fetchall()]
    if old_pids:
        ph = ",".join("?" * len(old_pids))
        conn.execute(f"DELETE FROM po_lines WHERE po_id IN (SELECT id FROM purchase_orders WHERE partner_id IN ({ph}))", old_pids)
        conn.execute(f"DELETE FROM quote_lines WHERE quote_id IN (SELECT id FROM quotations WHERE partner_id IN ({ph}))", old_pids)
        conn.execute(f"DELETE FROM so_lines WHERE so_id IN (SELECT id FROM sales_orders WHERE partner_id IN ({ph}))", old_pids)
        conn.execute(f"DELETE FROM sales_orders WHERE partner_id IN ({ph})", old_pids)
        conn.execute(f"DELETE FROM quotations WHERE partner_id IN ({ph})", old_pids)
        conn.execute(f"DELETE FROM purchase_orders WHERE partner_id IN ({ph})", old_pids)
    conn.execute("DELETE FROM tax_invoice_items WHERE invoice_id IN (SELECT id FROM tax_invoices WHERE company_id=?)", (book,))
    conn.execute("DELETE FROM tax_invoices WHERE company_id=?", (book,))
    old_docs = [r[0] for r in conn.execute(
        "SELECT id FROM erp_docs WHERE company_id=? AND source_type='seed'", (book,)).fetchall()]
    if old_docs:
        ph = ",".join("?" * len(old_docs))
        conn.execute(f"DELETE FROM slip_lines WHERE doc_id IN ({ph})", old_docs)
        conn.execute(f"DELETE FROM approval_lines WHERE doc_id IN ({ph})", old_docs)
        conn.execute(f"DELETE FROM doc_history WHERE doc_id IN ({ph})", old_docs)
        conn.execute(f"DELETE FROM erp_docs WHERE id IN ({ph})", old_docs)
    conn.execute("DELETE FROM partners WHERE company_id=? AND code LIKE 'S%'", (book,))
    conn.execute("DELETE FROM budgets WHERE company_id=?", (book,))
    conn.execute("DELETE FROM bank_accounts WHERE company_id=?", (book,))
    conn.execute("DELETE FROM fi_closings WHERE company_id=? AND year=?", (book, YEAR))


def make_partners(conn, book):
    pids = {}
    for i, (name, rep, btype, bitem, addr, ptype) in enumerate(PARTNERS, 1):
        pid = conn.execute(
            """INSERT INTO partners (company_id, code, name, biz_no, representative, biz_type, biz_item,
                   address, partner_type) VALUES (?,?,?,?,?,?,?,?,?)""",
            (book, f"S{i:03d}", name, calc_biz_no(i), rep, btype, bitem, addr, ptype),
        ).lastrowid
        pids[name] = pid
    return pids


def make_items(conn, book):
    ids = {}
    for code, name, itype, unit, price, _, _ in ITEMS:
        row = conn.execute("SELECT id FROM items WHERE item_code=? AND company_id=?", (code, book)).fetchone()
        if row:
            ids[code] = row[0]
            continue
        ids[code] = conn.execute(
            "INSERT INTO items (company_id, item_code, item_name, item_type, unit, unit_price) VALUES (?,?,?,?,?,?)",
            (book, code, name, itype, unit, price),
        ).lastrowid
    return ids


def make_bank_accounts(conn, book, uid):
    banks = [("기업은행", "354-011234-01-011", "보통예금(기업은행)"), ("국민은행", "581201-04-112233", "보통예금(국민은행)")]
    for bank, acc_no, name in banks:
        conn.execute(
            "INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code, created_by) VALUES (?,?,?,?,?,?)",
            (book, bank, acc_no, name, "103", uid),
        )


def close_month(conn, book, uid, year, month):
    conn.execute(
        """INSERT INTO fi_closings (company_id, year, month, status, closed_by, closed_at)
           VALUES (?,?,?,'closed',?,datetime('now','localtime'))
           ON CONFLICT(company_id, year, month) DO UPDATE SET
               status='closed', closed_by=excluded.closed_by, closed_at=excluded.closed_at,
               reopened_by=NULL, reopened_at=NULL, reopen_reason=NULL""",
        (book, year, month, uid),
    )


def make_sale(conn, book, uid, pid, name, d, item, rng):
    code, iname, itype, unit, price, qlo, qhi = item
    qty = rng.randint(qlo, qhi)
    unit_price = max(1, price + rng.randint(-int(price * 0.05), int(price * 0.08)))
    supply = qty * unit_price
    vat = supply // 10
    acct = "402" if itype == "product" else "401"
    inv = {"kind": "매출", "tax_type": "과세", "supply_amt": supply, "vat": vat, "partner_id": pid, "issue_date": d, "deduct": 1}
    lines = invoices.inv_lines(inv, acct, "110", f"{iname} 납품")
    doc_id = books.post(conn, book, uid, d, lines, f"{iname} 납품 - {name}", "seed", slip_type="매출")
    invoices.add(conn, book, uid, {**inv, "doc_id": doc_id, "evidence": "세금계산서"},
                 items=[{"name": iname, "spec": unit, "qty": qty, "unit_price": unit_price, "supply_amt": supply}])
    return doc_id, supply, vat


def make_purchase(conn, book, uid, pid, name, d, item, rng):
    code, iname, itype, unit, price, qlo, qhi = item
    qty = rng.randint(qlo, qhi)
    unit_price = max(1, int(price * rng.uniform(0.55, 0.72)))
    supply = qty * unit_price
    vat = supply // 10
    inv = {"kind": "매입", "tax_type": "과세", "supply_amt": supply, "vat": vat, "partner_id": pid, "issue_date": d, "deduct": 1}
    lines = invoices.inv_lines(inv, "452", "251", f"{iname} 매입")
    doc_id = books.post(conn, book, uid, d, lines, f"{iname} 매입 - {name}", "seed", slip_type="매입")
    invoices.add(conn, book, uid, {**inv, "doc_id": doc_id, "evidence": "세금계산서"},
                 items=[{"name": iname, "spec": unit, "qty": qty, "unit_price": unit_price, "supply_amt": supply}])
    return doc_id, supply, vat


def collect_ar(conn, book, uid, pid, name, d, amt):
    books.post(conn, book, uid, d, [
        {"code": "103", "debit": amt, "credit": 0, "partner_id": pid, "summary": f"{name} 매출대금 입금"},
        {"code": "110", "debit": 0, "credit": amt, "partner_id": pid, "summary": ""},
    ], f"{name} 매출대금 입금", "seed", slip_type="입금")


def pay_ap(conn, book, uid, pid, name, d, amt):
    books.post(conn, book, uid, d, [
        {"code": "251", "debit": amt, "credit": 0, "partner_id": pid, "summary": f"{name} 매입대금 결제"},
        {"code": "103", "debit": 0, "credit": amt, "partner_id": pid, "summary": ""},
    ], f"{name} 매입대금 결제", "seed", slip_type="출금")


def salary_lines(gross):
    tax = int(gross * 0.041)
    pension = int(gross * 0.045)
    health = int(gross * 0.0354)
    employ = int(gross * 0.009)
    net = gross - tax - pension - health - employ
    return [
        {"code": "801", "debit": gross, "credit": 0, "summary": "급여"},
        {"code": "103", "debit": 0, "credit": net, "summary": "실지급액"},
        {"code": "261", "debit": 0, "credit": tax, "summary": ""},
        {"code": "262", "debit": 0, "credit": pension, "summary": ""},
        {"code": "263", "debit": 0, "credit": health, "summary": ""},
        {"code": "264", "debit": 0, "credit": employ, "summary": ""},
    ], {"tax": tax, "pension": pension, "health": health, "employ": employ}


def raw_slip(conn, book, uid, reviewer, approver, d, slip_type, lines, title, status):
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    slip_no = books.next_slip_no(conn, book, d)
    total = sum(l["debit"] for l in lines)
    doc_status = "draft" if status == "draft" else "wait"
    uname = conn.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()["name"]
    doc_id = conn.execute(
        """INSERT INTO erp_docs (user_id, doc_type, title, status, slip_type, slip_date, slip_total,
               company_id, slip_no, doc_number, source_type)
           VALUES (?,'expense',?,?,?,?,?,?,?,?,'seed')""",
        (uid, title, doc_status, slip_type, d, total, book, slip_no, slip_no),
    ).lastrowid
    books.write_lines(conn, doc_id, book, lines)
    insert_approval_lines(conn, doc_id, uid, reviewer, approver, status == "draft", now, uname,
                          "임시저장" if status == "draft" else "기안")
    if status == "rejected":
        line = conn.execute("SELECT id FROM approval_lines WHERE doc_id=? AND step=1", (doc_id,)).fetchone()
        conn.execute("UPDATE approval_lines SET status='rejected', comment=?, acted_at=? WHERE id=?",
                     ("증빙 서류 확인 필요", now, line["id"]))
        conn.execute("UPDATE erp_docs SET status='rejected', reject_reason=? WHERE id=?", ("증빙 서류 확인 필요", doc_id))
        rname = conn.execute("SELECT name FROM users WHERE id=?", (reviewer,)).fetchone()["name"]
        conn.execute("INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
                     (doc_id, reviewer, rname, "반려", "증빙 서류 확인 필요"))
    return doc_id


def gen_slips(conn, book, uid, pids, days, rng, fa_partner):
    stats = {"sales": 0, "purchase": 0, "collect": 0, "pay": 0, "salary": 0, "rent": 0, "wht": 0,
             "ins4": 0, "util": 0, "tel": 0, "card": 0, "interest": 0, "fa": 0}

    books.post(conn, book, uid, START, [
        {"code": "103", "debit": 120000000, "credit": 0, "summary": "설립자본금 출자"},
        {"code": "331", "debit": 0, "credit": 120000000, "summary": ""},
    ], "설립자본금 출자", "seed", slip_type="대체")

    customers = [n for n, _, _, _, _, t in PARTNERS if t in ("customer", "both")]
    suppliers = [n for n, _, _, _, _, t in PARTNERS if t in ("supplier", "both")]
    sale_items = ITEMS
    buy_items = [it for it in ITEMS if it[0] in PURCHASE_CODES]

    # 채권/채무 연령분석 버킷을 확실히 채우기 위한 고정 미회수 건
    ar_anchor = ["2026-07-01", "2026-07-31", "2026-08-14", "2026-09-21"]
    ap_anchor = ["2026-07-01", "2026-07-31", "2026-08-20", "2026-09-24"]

    sale_days = sorted(rng.sample(days, 31)) + ar_anchor
    for d in sale_days:
        name = rng.choice(customers)
        pid = pids[name]
        item = rng.choice(sale_items)
        _, supply, vat = make_sale(conn, book, uid, pid, name, d, item, rng)
        stats["sales"] += 1
        if d not in ar_anchor and rng.random() < 0.62:
            pay_day = min(add_days(d, rng.randint(7, 25)), END)
            collect_ar(conn, book, uid, pid, name, pay_day, supply + vat)
            stats["collect"] += 1

    buy_days = sorted(rng.sample(days, 24)) + ap_anchor
    for d in buy_days:
        name = rng.choice(suppliers)
        pid = pids[name]
        item = rng.choice(buy_items)
        _, supply, vat = make_purchase(conn, book, uid, pid, name, d, item, rng)
        stats["purchase"] += 1
        if d not in ap_anchor and rng.random() < 0.58:
            pay_day = min(add_days(d, rng.randint(5, 20)), END)
            pay_ap(conn, book, uid, pid, name, pay_day, supply + vat)
            stats["pay"] += 1

    ins_carry = None
    for mon, pay_day in ((7, "2026-07-25"), (8, "2026-08-25"), (9, "2026-09-25")):
        gross = uneven(rng, 45000000, 51000000)
        lines, parts = salary_lines(gross)
        books.post(conn, book, uid, pay_day, lines, f"{mon}월 급여", "seed", slip_type="대체")
        stats["salary"] += 1

        # 전월 원천세/4대보험 신고납부 (다음달 10일)
        if ins_carry:
            wht_day = f"2026-{mon:02d}-10"
            books.post(conn, book, uid, wht_day, [
                {"code": "261", "debit": ins_carry["tax"], "credit": 0, "summary": "원천세 납부"},
                {"code": "103", "debit": 0, "credit": ins_carry["tax"], "summary": ""},
            ], "원천세 신고납부", "seed", slip_type="출금")
            stats["wht"] += 1
            emp_share = ins_carry["pension"] + ins_carry["health"] + ins_carry["employ"]
            books.post(conn, book, uid, wht_day, [
                {"code": "262", "debit": ins_carry["pension"], "credit": 0, "summary": ""},
                {"code": "263", "debit": ins_carry["health"], "credit": 0, "summary": ""},
                {"code": "264", "debit": ins_carry["employ"], "credit": 0, "summary": ""},
                {"code": "804", "debit": emp_share, "credit": 0, "summary": "회사부담분"},
                {"code": "103", "debit": 0, "credit": emp_share * 2, "summary": ""},
            ], "4대보험료 납부", "seed", slip_type="출금")
            stats["ins4"] += 1
        ins_carry = parts

        rent_day = f"2026-{mon:02d}-{28 if mon != 9 else 25}"
        rent_day = min(rent_day if rent_day in days else add_days(rent_day, 3), END)
        rent_amt = uneven(rng, 3600000, 3900000)
        books.post(conn, book, uid, rent_day, [
            {"code": "817", "debit": rent_amt, "credit": 0, "summary": f"{mon}월 사무실 임차료"},
            {"code": "103", "debit": 0, "credit": rent_amt, "summary": ""},
        ], f"{mon}월 사무실 임차료", "seed", slip_type="출금")
        stats["rent"] += 1

        util_day = min(add_days(f"2026-{mon:02d}-15", 0) if f"2026-{mon:02d}-15" in days else add_days(f"2026-{mon:02d}-15", 1), END)
        util_amt = uneven(rng, 150000, 260000)
        books.post(conn, book, uid, util_day, [
            {"code": "814", "debit": util_amt, "credit": 0, "summary": f"{mon}월 수도광열비"},
            {"code": "103", "debit": 0, "credit": util_amt, "summary": ""},
        ], f"{mon}월 수도광열비 납부", "seed", slip_type="출금")
        stats["util"] += 1

        tel_amt = uneven(rng, 260000, 320000)
        books.post(conn, book, uid, util_day, [
            {"code": "813", "debit": tel_amt, "credit": 0, "summary": f"{mon}월 통신비"},
            {"code": "103", "debit": 0, "credit": tel_amt, "summary": ""},
        ], f"{mon}월 통신비 납부", "seed", slip_type="출금")
        stats["tel"] += 1

        int_day = min(f"2026-{mon:02d}-20" if f"2026-{mon:02d}-20" in days else add_days(f"2026-{mon:02d}-20", 1), END)
        int_amt = uneven(rng, 300000, 450000)
        books.post(conn, book, uid, int_day, [
            {"code": "951", "debit": int_amt, "credit": 0, "summary": f"{mon}월 차입금 이자"},
            {"code": "103", "debit": 0, "credit": int_amt, "summary": ""},
        ], f"{mon}월 이자비용 지급", "seed", slip_type="출금")
        stats["interest"] += 1

    card_days = sorted(rng.sample(days, 18))
    for d in card_days:
        acct = rng.choice(CARD_ACCTS)
        amt = uneven(rng, 30000, 850000)
        label = {"804": "복리후생비", "811": "여비교통비", "812": "접대비", "820": "소모품비",
                 "821": "지급수수료", "835": "차량유지비", "833": "교육훈련비", "834": "도서인쇄비"}[acct]
        books.post(conn, book, uid, d, [
            {"code": acct, "debit": amt, "credit": 0, "summary": label},
            {"code": "103", "debit": 0, "credit": amt, "summary": ""},
        ], f"{label} 지출", "seed", slip_type="출금")
        stats["card"] += 1

    fa_day = "2026-08-05" if "2026-08-05" in days else add_days("2026-08-05", 1)
    fa_supply = 8200000
    fa_vat = fa_supply // 10
    inv = {"kind": "매입", "tax_type": "과세", "supply_amt": fa_supply, "vat": fa_vat,
           "partner_id": fa_partner, "issue_date": fa_day, "deduct": 1}
    lines = invoices.inv_lines(inv, "206", "103", "생산설비 교체")
    doc_id = books.post(conn, book, uid, fa_day, lines, "생산설비 일부 교체", "seed", slip_type="출금")
    invoices.add(conn, book, uid, {**inv, "doc_id": doc_id, "evidence": "세금계산서"},
                 items=[{"name": "SMT 실장설비 부속", "qty": 1, "unit_price": fa_supply, "supply_amt": fa_supply}])
    stats["fa"] += 1

    return stats


def make_drafts(conn, book, drafter, reviewer, approver, days):
    raw_slip(conn, book, drafter, reviewer, approver, "2026-09-14", "대체", [
        {"code": "820", "debit": 428000, "credit": 0, "summary": "사무용품 구입"},
        {"code": "103", "debit": 0, "credit": 428000, "summary": ""},
    ], "사무용품 구입 (임시저장)", "draft")
    raw_slip(conn, book, drafter, reviewer, approver, "2026-09-16", "대체", [
        {"code": "811", "debit": 185000, "credit": 0, "summary": "출장비 정산"},
        {"code": "103", "debit": 0, "credit": 185000, "summary": ""},
    ], "출장비 정산 (임시저장)", "draft")
    raw_slip(conn, book, drafter, reviewer, approver, "2026-09-18", "대체", [
        {"code": "812", "debit": 340000, "credit": 0, "summary": "거래처 접대"},
        {"code": "103", "debit": 0, "credit": 340000, "summary": ""},
    ], "접대비 지출결의 (결재대기)", "wait")
    raw_slip(conn, book, drafter, reviewer, approver, "2026-09-21", "대체", [
        {"code": "821", "debit": 260000, "credit": 0, "summary": "외주 용역 수수료"},
        {"code": "103", "debit": 0, "credit": 260000, "summary": ""},
    ], "지급수수료 지출결의 (결재대기)", "wait")
    raw_slip(conn, book, drafter, reviewer, approver, "2026-09-09", "대체", [
        {"code": "835", "debit": 512000, "credit": 0, "summary": "차량 정비"},
        {"code": "103", "debit": 0, "credit": 512000, "summary": ""},
    ], "차량유지비 지출결의 (반려)", "rejected")
    raw_slip(conn, book, drafter, reviewer, approver, "2026-09-11", "대체", [
        {"code": "834", "debit": 96000, "credit": 0, "summary": "교육 교재 구입"},
        {"code": "103", "debit": 0, "credit": 96000, "summary": ""},
    ], "도서인쇄비 지출결의 (반려)", "rejected")


def next_num(conn, prefix, table, col):
    row = conn.execute(
        f"SELECT {col} FROM {table} WHERE {col} LIKE ? ORDER BY id DESC LIMIT 1", (f"{prefix}-{YEAR}-%",)
    ).fetchone()
    seq = int(row[0].split("-")[-1]) + 1 if row else 1
    return f"{prefix}-{YEAR}-{seq:04d}"


def item_row(conn, code, book):
    return conn.execute("SELECT id FROM items WHERE item_code=? AND company_id=?", (code, book)).fetchone()[0]


def make_po_quotes(conn, book, uid, pids):
    suppliers = [n for n, _, _, _, _, t in PARTNERS if t in ("supplier", "both")]
    customers = [n for n, _, _, _, _, t in PARTNERS if t in ("customer", "both")]
    buy_items = [it for it in ITEMS if it[0] in PURCHASE_CODES]

    po_specs = [
        ("2026-07-10", "draft", suppliers[0], buy_items[0], 400),
        ("2026-07-20", "pending_approval", suppliers[1], buy_items[1], 300),
        ("2026-08-05", "confirmed", suppliers[2], buy_items[2], 150),
        ("2026-08-25", "partial", suppliers[3], buy_items[3], 80),
        ("2026-09-10", "completed", suppliers[4 % len(suppliers)], buy_items[4], 250),
    ]
    for po_date, status, sname, item, qty in po_specs:
        code, price = item[0], item[4]
        item_id = item_row(conn, code, book)
        unit_price = int(price * 0.65)
        total = qty * unit_price
        num = next_num(conn, "PO", "purchase_orders", "po_number")
        po_id = conn.execute(
            """INSERT INTO purchase_orders (po_number, partner_id, po_date, delivery_date, status,
                   total_amount, tax_amount, notes, created_by, company_id) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (num, pids[sname], po_date, add_days(po_date, 14), status, total, total // 10, "", uid, book),
        ).lastrowid
        conn.execute(
            "INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,?,?,?)",
            (po_id, item_id, qty, unit_price, total),
        )

    quote_specs = [
        ("2026-07-15", "draft", customers[0], ITEMS[4], 200),
        ("2026-08-01", "sent", customers[1], ITEMS[5], 150),
        ("2026-08-12", "accepted", customers[2], ITEMS[9], 60),
        ("2026-09-05", "rejected", customers[3], ITEMS[0], 500),
    ]
    for quote_date, status, cname, item, qty in quote_specs:
        code, price = item[0], item[4]
        item_id = item_row(conn, code, book)
        unit_price = price
        total = qty * unit_price
        num = next_num(conn, "QT", "quotations", "quote_number")
        qt_id = conn.execute(
            """INSERT INTO quotations (quote_number, partner_id, quote_date, valid_until, status,
                   total_amount, tax_amount, notes, created_by, company_id) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (num, pids[cname], quote_date, add_days(quote_date, 30), status, total, total // 10, "", uid, book),
        ).lastrowid
        conn.execute(
            "INSERT INTO quote_lines (quote_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,?,?,?)",
            (qt_id, item_id, qty, price, total),
        )
        if status == "accepted":
            so_num = next_num(conn, "SO", "sales_orders", "so_number")
            so_id = conn.execute(
                """INSERT INTO sales_orders (so_number, quote_id, partner_id, order_date, delivery_date,
                       status, total_amount, tax_amount, notes, created_by, company_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (so_num, qt_id, pids[cname], add_days(quote_date, 3), add_days(quote_date, 17),
                 "shipped", total, total // 10, f"견적 {num} 기반", uid, book),
            ).lastrowid
            conn.execute(
                "INSERT INTO so_lines (so_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,?,?,?)",
                (so_id, item_id, qty, price, total),
            )

    so_num = next_num(conn, "SO", "sales_orders", "so_number")
    code, iname, itype, unit, price, qlo, qhi = ITEMS[6]
    item_id = item_row(conn, code, book)
    qty = 320
    total = qty * price
    so_id = conn.execute(
        """INSERT INTO sales_orders (so_number, partner_id, order_date, delivery_date, status,
               total_amount, tax_amount, notes, created_by, company_id) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (so_num, pids[customers[4 % len(customers)]], "2026-09-08", "2026-09-22", "confirmed", total, total // 10, "", uid, book),
    ).lastrowid
    conn.execute(
        "INSERT INTO so_lines (so_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,?,?,?)",
        (so_id, item_id, qty, price, total),
    )


def make_budgets(conn, book, uid):
    plan = {"452": 16000000, "801": 48000000, "804": 3200000, "811": 900000, "813": 300000,
            "814": 220000, "817": 3800000, "820": 500000, "821": 700000, "835": 450000, "951": 380000}
    for code, amt in plan.items():
        for m in range(1, 13):
            conn.execute(
                """INSERT INTO budgets (company_id, account_code, year, month, amount, created_by)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(company_id, account_code, year, month) DO UPDATE SET amount=?, created_by=?""",
                (book, code, YEAR, m, amt, uid, amt, uid),
            )


def run(conn, book):
    drafter, reviewer, approver = pick_users(conn, book)
    clear_seed(conn, book)
    books.seed_accounts(conn, book)
    pids = make_partners(conn, book)
    make_items(conn, book)
    make_bank_accounts(conn, book, drafter)
    days = biz_days(START, END)
    rng = random.Random(9000 + book)
    suppliers = [n for n, _, _, _, _, t in PARTNERS if t in ("supplier", "both")]
    fa_partner = pids[suppliers[5 % len(suppliers)]]
    stats = gen_slips(conn, book, drafter, pids, days, rng, fa_partner)
    make_drafts(conn, book, drafter, reviewer, approver, days)
    make_po_quotes(conn, book, drafter, pids)
    make_budgets(conn, book, drafter)
    close_month(conn, book, drafter, 2026, 7)
    close_month(conn, book, drafter, 2026, 8)
    conn.commit()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", type=int, default=1)
    ap.add_argument("--db", required=True)
    args = ap.parse_args()
    # 운영 DB에 시드 들어가면 실장부 오염
    if os.getenv("ENV") == "production":
        raise SystemExit("운영 환경에서는 시드 실행 불가")
    dbmod.DB_PATH = args.db
    conn = dbmod.get_sqlite()
    stats = run(conn, args.company)

    print(f"완료: company_id={args.company}")
    for k, v in stats.items():
        print(f"  {k}: {v}건")

    docs = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(slip_total),0) FROM erp_docs WHERE company_id=? AND source_type='seed'",
        (args.company,),
    ).fetchone()
    print(f"  전표 총 {docs[0]}건, 합계 {docs[1]:,}원")
    inv_cnt = conn.execute("SELECT COUNT(*) FROM tax_invoices WHERE company_id=?", (args.company,)).fetchone()[0]
    print(f"  세금계산서 {inv_cnt}건")

    bal = conn.execute(
        """SELECT COALESCE(SUM(sl.debit),0), COALESCE(SUM(sl.credit),0) FROM slip_lines sl
           JOIN erp_docs d ON d.id=sl.doc_id WHERE d.company_id=? AND d.status='done'""",
        (args.company,),
    ).fetchone()
    print(f"  차변 합계 {bal[0]:,} / 대변 합계 {bal[1]:,}")


if __name__ == "__main__":
    main()

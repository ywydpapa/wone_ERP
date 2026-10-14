import calendar
import json
from datetime import date, timedelta

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from core.deps import get_db
from core.books import require_book
from core import credit

KINDS = {"general": "일반", "finance": "금융", "card": "카드사"}
REG_KINDS = {"biz": "사업자", "rrn": "주민", "foreign": "외국인"}
BIZ_STATUS = {"normal": "정상", "suspended": "휴업", "closed": "폐업"}
TRADE_STATUS = {"active": "거래중", "hold": "거래보류", "stop": "거래중지"}
TRADE_CLASS = {"active": "status-done", "hold": "status-wait", "stop": "status-reject"}
PAY_TERMS = {"": "미지정", "cash": "현금", "days": "거래일로부터 N일", "eom": "월말 마감 후 N일"}
ROLES = {"sales": "영업", "buy": "구매", "acct": "회계", "tax": "세금계산서", "etc": "기타"}

# 사업자번호 10자리 검증번호 가중치
BIZ_W = (1, 3, 7, 1, 3, 7, 1, 3, 5)

ALERTS = {"over_limit": "여신초과", "overdue": "결제지연", "no_sale": "매출없음",
          "no_act": "활동없음", "closed_bal": "휴폐업 잔액"}
ALERT_DEFAULTS = {"over_limit": 1, "overdue": 30, "no_sale": 90, "no_act": 60, "closed_bal": 1}

FIELDS = {
    "code": "거래처코드", "name": "거래처명", "kind": "거래처구분", "reg_kind": "등록구분",
    "biz_no": "사업자번호", "tax_type": "과세유형", "rep_id": "담당사원", "sub_rep_id": "부담당",
    "credit_limit": "여신한도", "credit_days": "여신기간", "pay_terms": "결제조건",
    "trade_status": "거래상태", "biz_status": "사업자상태", "group_id": "거래처그룹",
    "is_active": "사용여부", "address": "주소", "bank": "계좌",
}


def digits(v):
    return "".join(c for c in (v or "") if c.isdigit())


def fmt_phone(v):
    d = digits(v)
    if d.startswith("02") and len(d) in (9, 10):
        return f"02-{d[2:-4]}-{d[-4:]}"
    if d.startswith("0") and len(d) in (10, 11):
        return f"{d[:3]}-{d[3:-4]}-{d[-4:]}"
    if len(d) == 8 and d[0] == "1":
        return f"{d[:4]}-{d[4:]}"
    return (v or "").strip()


def mask_reg(v):
    d = digits(v)
    if len(d) == 13:
        return f"{d[:6]}-{d[6]}" + "*" * 6
    return v


def due_date(day_iso, terms, days):
    d = date.fromisoformat(day_iso)
    if terms == "days":
        return (d + timedelta(days=days)).isoformat()
    if terms == "eom":
        last = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
        return (last + timedelta(days=days)).isoformat()
    return day_iso


# 사업자번호 10자리 검증. 13자리 법인/개인 통과는 등록구분이 사업자인 경우 불허
def validate_biz_no(v):
    d = digits(v)
    if not d:
        return "", None
    if len(d) != 10:
        return None, "사업자번호는 10자리로 입력해 주세요."
    n = sum(int(d[i]) * BIZ_W[i] for i in range(9)) + int(d[8]) * 5 // 10
    if (10 - n % 10) % 10 != int(d[9]):
        return None, "사업자번호가 올바르지 않습니다."
    return f"{d[:3]}-{d[3:5]}-{d[5:]}", None


# 2020.10. 이후 발급분부터 검증번호 제도 폐지. 형식(생년월일, 성별코드)만 확인
def validate_rrn(v):
    d = digits(v)
    if not d:
        return "", None
    if len(d) != 13:
        return None, "주민등록번호는 13자리로 입력해 주세요."
    try:
        date(2000, int(d[2:4]), int(d[4:6]))
    except ValueError:
        return None, "생년월일이 올바르지 않습니다."
    if d[6] not in "12345678":
        return None, "주민등록번호 7번째 숫자가 올바르지 않습니다."
    return f"{d[:6]}-{d[6:]}", None


def validate_foreign(v):
    v = (v or "").strip()
    if len(v) > 20:
        return None, "외국인등록번호는 20자 이내로 입력해 주세요."
    return v, None


def validate_reg_no(reg_kind, v):
    if reg_kind == "biz":
        return validate_biz_no(v)
    if reg_kind == "rrn":
        return validate_rrn(v)
    if reg_kind == "foreign":
        return validate_foreign(v)
    return (v or "").strip(), None


# 타 거래처, 타 회사 담당자 id는 무시
def own_contact(conn, book, pid, cid):
    cid = int(cid) if str(cid or "").isdigit() else 0
    if cid and pid and conn.execute("SELECT 1 FROM partner_contacts WHERE id=? AND partner_id=? AND company_id=?",
                                    (cid, pid, book)).fetchone():
        return cid
    return None


def can_edit(u):
    return u["role"] in ("client", "platform_staff")


def require_editor(request: Request, conn=Depends(get_db)):
    u = require_book(request, conn)
    if not can_edit(u):
        raise HTTPException(status_code=403)
    return u


# 거래중지/거래보류, 휴폐업, 여신 경고를 하나로 묶어 반환. on_date 형식 오류는 credit.check와 동일하게 예외 발생
# 여신은 매출채권 기준이므로 매입 문서는 ar=False로 제외
def guard(conn, book, pid, amount, on_date, doc, ar=True):
    date.fromisoformat(on_date)
    p = conn.execute(
        "SELECT name, trade_status, biz_status, biz_checked_at FROM partners WHERE id=? AND company_id=?",
        (pid, book),
    ).fetchone()
    if not p:
        return None
    msgs, block = [], False

    if p["trade_status"] == "stop":
        msgs.append(f"거래중지 거래처입니다. 신규 {doc} 입력이 제한됩니다.")
        block = True
    elif p["trade_status"] == "hold":
        msgs.append(f"거래보류 거래처입니다. {doc} 입력 전 확인이 필요합니다.")

    if p["biz_status"] in ("suspended", "closed"):
        chk = f" (확인일 {p['biz_checked_at']})" if p["biz_checked_at"] else ""
        msgs.append(f"{BIZ_STATUS[p['biz_status']]} 상태 거래처입니다{chk}.")

    cr = ar and credit.check(conn, book, pid, amount, on_date)
    if cr:
        msgs.append(cr["msg"])
        block = block or cr["block"]

    if not msgs:
        return None
    return {"msg": "\n\n".join(msgs), "block": block}


# 경고 모드는 confirm 응답 후 화면에서 credit_ok로 재전송
def credit_reply(over):
    if over["block"]:
        return JSONResponse({"notice": over["msg"] + "\n\n저장할 수 없습니다."}, status_code=400)
    return JSONResponse({"confirm": over["msg"] + "\n\n저장하겠습니까?"}, status_code=409)


def alert_cfg(conn, book):
    row = conn.execute("SELECT partner_alerts FROM client_companies WHERE id=?", (book,)).fetchone()
    cfg = dict(ALERT_DEFAULTS)
    if row and row["partner_alerts"]:
        try:
            cfg.update(json.loads(row["partner_alerts"]))
        except (ValueError, TypeError):
            pass
    return cfg


# 거래처별 반복 조회 대신 집계 질의로 일괄 산정
def alerts(conn, book, today_iso):
    cfg = alert_cfg(conn, book)
    partners = {r["id"]: dict(r) for r in conn.execute(
        """SELECT id, partner_type, credit_limit, trade_status, biz_status, pay_terms, pay_days
           FROM partners WHERE company_id=? AND is_active=1 AND merged_into IS NULL""", (book,))}
    if not partners:
        return {}
    result = {pid: [] for pid in partners}

    def bal_by_partner(acct):
        rows = conn.execute(
            """SELECT COALESCE(sl.partner_id, mp.id) AS pid, SUM(sl.debit) - SUM(sl.credit) AS bal
                FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
                LEFT JOIN partners mp ON mp.company_id=d.company_id AND mp.name=sl.partner AND sl.partner_id IS NULL
                WHERE d.company_id=? AND d.status='done' AND sl.account_code=?
                GROUP BY pid""", (book, acct),
        ).fetchall()
        return {r["pid"]: r["bal"] for r in rows if r["pid"] in partners}

    ar = bal_by_partner("110")

    if cfg["over_limit"]:
        for pid, p in partners.items():
            if p["credit_limit"] > 0 and ar.get(pid, 0) > p["credit_limit"]:
                result[pid].append("over_limit")

    if cfg["overdue"]:
        open_ar = credit.open_items(conn, book, "110")
        for pid, info in open_ar.items():
            p = partners.get(pid)
            if not p:
                continue
            for it in info["items"]:
                due = due_date(it["date"], p["pay_terms"], p["pay_days"])
                cutoff = (date.fromisoformat(due) + timedelta(days=cfg["overdue"])).isoformat()
                if cutoff < today_iso:
                    result[pid].append("overdue")
                    break

    if cfg["no_sale"]:
        cutoff = (date.fromisoformat(today_iso) - timedelta(days=cfg["no_sale"])).isoformat()
        last_sale = {r["partner_id"]: r["last"] for r in conn.execute(
            """SELECT partner_id, MAX(issue_date) AS last FROM tax_invoices
               WHERE company_id=? AND kind='매출' GROUP BY partner_id""", (book,))}
        for pid, p in partners.items():
            if p["partner_type"] not in ("customer", "both") or p["trade_status"] != "active":
                continue
            last = last_sale.get(pid)
            if last and last < cutoff:
                result[pid].append("no_sale")

    if cfg["no_act"]:
        cutoff = (date.fromisoformat(today_iso) - timedelta(days=cfg["no_act"])).isoformat()
        last_act = {r["partner_id"]: r["last"] for r in conn.execute(
            "SELECT partner_id, MAX(act_date) AS last FROM crm_activities WHERE company_id=? GROUP BY partner_id",
            (book,))}
        # 활동 이력 없는 거래처 제외
        for pid, last in last_act.items():
            if pid in partners and last and last < cutoff:
                result[pid].append("no_act")

    if cfg["closed_bal"]:
        ap = bal_by_partner("251")
        for pid, p in partners.items():
            if p["biz_status"] in ("suspended", "closed") and (ar.get(pid, 0) or ap.get(pid, 0)):
                result[pid].append("closed_bal")

    return {pid: codes for pid, codes in result.items() if codes}


def log_changes(conn, book, pid, uid, old, new):
    for f in FIELDS:
        if f not in old and f not in new:
            continue
        o, n = old.get(f, ""), new.get(f, "")
        if o != n:
            conn.execute(
                "INSERT INTO partner_history (company_id, partner_id, field, old, new, user_id) VALUES (?,?,?,?,?,?)",
                (book, pid, f, o, n, uid),
            )

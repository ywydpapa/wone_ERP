# 사용자별 메뉴 그룹 권한 매트릭스. 역할 기본 권한보다 낮추는 용도만

from fastapi import HTTPException, Request

from core.db import get_sqlite

GROUPS = {"work": "업무", "fi": "회계", "hr": "인사/급여", "mm": "구매/재고", "sales": "생산/영업", "admin": "관리"}

GROUP_OF_PATH = [
    ("/erp_dash", "work"),
    ("/erp_groupware", "sales"),
    ("/erp_product", "sales"),
    ("/erp_hr", "hr"),
    ("/erp_fa", "fi"),
    ("/erp_inventory", "mm"),
    ("/erp_purch", "mm"),
    ("/platform/work-requests", "work"),
    ("/daily-report", "work"),
    ("/platform/help-requests", "work"),
    ("/platform/companies", "work"),
    ("/platform/monthly-report", "work"),
    ("/platform/export-templates", "work"),
    ("/platform/export-logs", "work"),
    ("/fi", "fi"),
    ("/bank-accounts", "fi"),
    ("/bank-txns", "fi"),
    ("/memo-codes", "fi"),
    ("/slip_entry", "fi"),
    ("/new_slip_simple", "fi"),
    ("/slip_list", "fi"),
    ("/api/slip", "fi"),
    ("/ledger", "fi"),
    ("/report", "fi"),
    ("/budget", "fi"),
    ("/tax-invoices", "fi"),
    ("/tax", "fi"),
    ("/fa", "fi"),
    ("/settlements", "fi"),
    ("/hr", "hr"),
    ("/payroll", "hr"),
    ("/pay-items", "hr"),
    ("/severance", "hr"),
    ("/roster", "hr"),
    ("/withholding", "hr"),
    ("/insurance-reports", "hr"),
    ("/leave_approvals", "hr"),
    ("/purchase-requisitions", "mm"),
    ("/purchase-orders", "mm"),
    ("/rfqs", "mm"),
    ("/goods-receipts", "mm"),
    ("/items", "mm"),
    ("/warehouses", "mm"),
    ("/stock", "mm"),
    ("/partners", "mm"),
    ("/work-orders", "sales"),
    ("/bom", "sales"),
    ("/quotations", "sales"),
    ("/sales-orders", "sales"),
    ("/shipments", "sales"),
    ("/erp_scrm", "sales"),
    ("/crm", "sales"),
    ("/partners/contacts", "sales"),
    ("/draft_doc", "sales"),
    ("/approvals", "sales"),
    ("/approval-lines", "sales"),
    ("/users", "admin"),
    ("/audit", "admin"),
    ("/settings/backup", "admin"),
]

_SORTED_PATHS = sorted(GROUP_OF_PATH, key=lambda t: -len(t[0]))


def group_of_path(path):
    for prefix, group in _SORTED_PATHS:
        if path == prefix or (path.startswith(prefix) and path[len(prefix):len(prefix) + 1] in ("/", "?")):
            return group
    return None


def level(conn, uid, group):
    row = conn.execute(
        "SELECT level FROM user_perms WHERE user_id=? AND group_key=?", (uid, group)
    ).fetchone()
    return row["level"] if row else "edit"


def check_perm(request: Request):
    uid = request.session.get("id")
    if not uid or not request.session.get("logined"):
        return
    group = group_of_path(request.url.path)
    if not group:
        return
    conn = get_sqlite()
    try:
        lv = level(conn, uid, group)
    finally:
        conn.close()
    if request.method in ("GET", "HEAD"):
        if lv == "none":
            raise HTTPException(status_code=403, detail="no_perm")
    elif lv != "edit":
        raise HTTPException(status_code=403, detail="no_perm")

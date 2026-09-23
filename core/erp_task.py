# ERP 태스크 자동 실적 조회

ERP_QUERY_MAP = {
    "slip_purchase": {
        "table": "erp_docs", "id_col": "user_id", "date_col": "slip_date",
        "filter": "doc_type='expense'",
        "cols": ["id", "doc_number", "title", "slip_date", "slip_total", "status"],
        "link": "/erp_doc/", "label": "전표",
    },
    "slip_sales": {
        "table": "erp_docs", "id_col": "user_id", "date_col": "slip_date",
        "filter": "doc_type='expense'",
        "cols": ["id", "doc_number", "title", "slip_date", "slip_total", "status"],
        "link": "/erp_doc/", "label": "전표",
    },
    "slip_expense": {
        "table": "erp_docs", "id_col": "user_id", "date_col": "slip_date",
        "filter": "doc_type='expense'",
        "cols": ["id", "doc_number", "title", "slip_date", "slip_total", "status"],
        "link": "/erp_doc/", "label": "전표",
    },
    "po_entry": {
        "table": "purchase_orders", "id_col": "created_by", "date_col": "order_date",
        "filter": "",
        "cols": ["id", "po_number", "order_date", "total_amount", "status"],
        "link": "/purchase-orders/", "label": "발주서",
    },
    "pr_entry": {
        "table": "purchase_requisitions", "id_col": "created_by", "date_col": "request_date",
        "filter": "",
        "cols": ["id", "pr_number", "request_date", "total_amount", "status"],
        "link": "/purchase-requisitions/", "label": "구매요청",
    },
    "gr_entry": {
        "table": "goods_receipts", "id_col": "created_by", "date_col": "receipt_date",
        "filter": "",
        "cols": ["id", "gr_number", "receipt_date", "status"],
        "link": "/goods-receipts/", "label": "입고",
    },
    "quote_entry": {
        "table": "quotations", "id_col": "created_by", "date_col": "quote_date",
        "filter": "",
        "cols": ["id", "quote_number", "quote_date", "total_amount", "status"],
        "link": "/quotations/", "label": "견적서",
    },
    "so_entry": {
        "table": "sales_orders", "id_col": "created_by", "date_col": "order_date",
        "filter": "",
        "cols": ["id", "so_number", "order_date", "total_amount", "status"],
        "link": "/sales-orders/", "label": "수주",
    },
    "ship_entry": {
        "table": "shipments", "id_col": "created_by", "date_col": "ship_date",
        "filter": "",
        "cols": ["id", "ship_number", "ship_date", "status"],
        "link": "/shipments/", "label": "출고",
    },
    "wo_entry": {
        "table": "work_orders", "id_col": "created_by", "date_col": "created_at",
        "filter": "",
        "cols": ["id", "wo_number", "planned_qty", "actual_qty", "status"],
        "link": "/work-orders/", "label": "작업지시",
    },
    "bom_entry": {
        "table": "bom_headers", "id_col": "created_by", "date_col": "created_at",
        "filter": "",
        "cols": ["id", "bom_number", "item_id", "version", "status"],
        "link": "/bom/", "label": "BOM",
    },
    "item_entry": {
        "table": "items", "id_col": "created_by", "date_col": "created_at",
        "filter": "",
        "cols": ["id", "item_code", "item_name", "item_type"],
        "link": "/items/", "label": "품목",
    },
    "partner_entry": {
        "table": "partners", "id_col": "created_by", "date_col": "created_at",
        "filter": "",
        "cols": ["id", "code", "name", "partner_type"],
        "link": "/partners/", "label": "거래처",
    },
}


def get_worker_uid(conn, emp_id):
    row = conn.execute("SELECT user_id FROM employees WHERE id=?", (emp_id,)).fetchone()
    return row["user_id"] if row else None


def get_erp_deliverables(conn, task):
    module = task.get("erp_module")
    if not module or module not in ERP_QUERY_MAP:
        return None

    spec = ERP_QUERY_MAP[module]
    uid = get_worker_uid(conn, task["assigned_to"])
    if not uid:
        return None

    dt_from = (task.get("created_at") or "2000-01-01")[:10]
    dt_to = task.get("due_date") or "9999-12-31"

    cols = ", ".join(spec["cols"])
    where = f"{spec['id_col']}=? AND {spec['date_col']} BETWEEN ? AND ?"
    if spec["filter"]:
        where += f" AND {spec['filter']}"

    rows = conn.execute(
        f"SELECT {cols} FROM {spec['table']} WHERE {where} ORDER BY {spec['date_col']} DESC",
        (uid, dt_from, dt_to),
    ).fetchall()

    return {
        "label": spec["label"],
        "count": len(rows),
        "rows": [dict(r) for r in rows],
        "cols": [c for c in spec["cols"] if c != "id"],
        "link": spec["link"],
    }


def sync_erp_volume(conn, task):
    result = get_erp_deliverables(conn, task)
    if result is None:
        return
    cnt = result["count"]
    if cnt != (task.get("completed_volume") or 0):
        conn.execute("UPDATE tasks SET completed_volume=? WHERE id=?", (cnt, task["id"]))

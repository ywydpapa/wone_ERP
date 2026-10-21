# ERP 태스크 자동 실적 조회

# 모듈별 상태값 통합. 실적 요약 표시용
CODE_LABELS = {
    "draft": "임시저장", "wait": "결재대기", "pending_approval": "결재대기", "progress": "결재중",
    "urgent": "긴급", "done": "완료", "approved": "승인", "rejected": "반려", "withdrawn": "철회",
    "confirmed": "확정", "partial": "부분입고", "completed": "완료", "cancelled": "취소",
    "sent": "발송", "accepted": "수락", "expired": "만료", "picking": "출고준비", "shipped": "출고완료",
    "invoiced": "청구완료", "planned": "계획", "released": "착수", "in_progress": "진행중",
    "active": "사용", "inactive": "미사용",
    "material": "원재료", "product": "완제품", "semi": "반제품", "consumable": "소모품",
    "customer": "매출처", "supplier": "매입처", "both": "매입매출",
}
AMT_COLS = {"slip_total", "total_amount"}
CODE_COLS = {"status", "item_type", "partner_type"}

ERP_QUERY_MAP = {
    "slip_purchase": {
        "table": "erp_docs", "id_col": "user_id", "date_col": "slip_date",
        "filter": "doc_type='expense'",
        "cols": [("doc_number", "전표번호"), ("title", "적요"), ("slip_date", "전표일자"), ("slip_total", "금액"), ("status", "상태")],
        "link": "/erp_doc/", "label": "전표",
    },
    "slip_sales": {
        "table": "erp_docs", "id_col": "user_id", "date_col": "slip_date",
        "filter": "doc_type='expense'",
        "cols": [("doc_number", "전표번호"), ("title", "적요"), ("slip_date", "전표일자"), ("slip_total", "금액"), ("status", "상태")],
        "link": "/erp_doc/", "label": "전표",
    },
    "slip_expense": {
        "table": "erp_docs", "id_col": "user_id", "date_col": "slip_date",
        "filter": "doc_type='expense'",
        "cols": [("doc_number", "전표번호"), ("title", "적요"), ("slip_date", "전표일자"), ("slip_total", "금액"), ("status", "상태")],
        "link": "/erp_doc/", "label": "전표",
    },
    "po_entry": {
        "table": "purchase_orders", "id_col": "created_by", "date_col": "order_date",
        "filter": "",
        "cols": [("po_number", "발주번호"), ("order_date", "발주일자"), ("total_amount", "금액"), ("status", "상태")],
        "link": "/purchase-orders/", "label": "발주서",
    },
    "pr_entry": {
        "table": "purchase_requisitions", "id_col": "created_by", "date_col": "request_date",
        "filter": "",
        "cols": [("pr_number", "요청번호"), ("request_date", "요청일자"), ("total_amount", "금액"), ("status", "상태")],
        "link": "/purchase-requisitions/", "label": "구매요청",
    },
    "gr_entry": {
        "table": "goods_receipts", "id_col": "created_by", "date_col": "receipt_date",
        "filter": "",
        "cols": [("gr_number", "입고번호"), ("receipt_date", "입고일자"), ("status", "상태")],
        "link": "/goods-receipts/", "label": "입고",
    },
    "quote_entry": {
        "table": "quotations", "id_col": "created_by", "date_col": "quote_date",
        "filter": "",
        "cols": [("quote_number", "견적번호"), ("quote_date", "견적일자"), ("total_amount", "금액"), ("status", "상태")],
        "link": "/quotations/", "label": "견적서",
    },
    "so_entry": {
        "table": "sales_orders", "id_col": "created_by", "date_col": "order_date",
        "filter": "",
        "cols": [("so_number", "수주번호"), ("order_date", "수주일자"), ("total_amount", "금액"), ("status", "상태")],
        "link": "/sales-orders/", "label": "수주",
    },
    "ship_entry": {
        "table": "shipments", "id_col": "created_by", "date_col": "ship_date",
        "filter": "",
        "cols": [("ship_number", "출고번호"), ("ship_date", "출고일자"), ("status", "상태")],
        "link": "/shipments/", "label": "출고",
    },
    "wo_entry": {
        "table": "work_orders", "id_col": "created_by", "date_col": "created_at",
        "filter": "",
        "cols": [("wo_number", "지시번호"), ("planned_qty", "계획수량"), ("actual_qty", "실적수량"), ("status", "상태")],
        "link": "/work-orders/", "label": "작업지시",
    },
    "bom_entry": {
        "table": "bom_headers", "id_col": "created_by", "date_col": "created_at",
        "filter": "",
        "cols": [("bom_number", "BOM번호"), ("item_id", "품목"), ("version", "버전"), ("status", "상태")],
        "link": "/bom/", "label": "BOM",
    },
    "item_entry": {
        "table": "items", "id_col": "created_by", "date_col": "created_at",
        "filter": "",
        "cols": [("item_code", "품목코드"), ("item_name", "품목명"), ("item_type", "품목구분")],
        "link": "/items/", "label": "품목",
    },
    "partner_entry": {
        "table": "partners", "id_col": "created_by", "date_col": "created_at",
        "filter": "",
        "cols": [("code", "거래처코드"), ("name", "거래처명"), ("partner_type", "거래처구분")],
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

    cols = ", ".join(["id"] + [c for c, _ in spec["cols"]])
    where = f"{spec['id_col']}=? AND {spec['date_col']} BETWEEN ? AND ?"
    if spec["filter"]:
        where += f" AND {spec['filter']}"

    rows = conn.execute(
        f"SELECT {cols} FROM {spec['table']} WHERE {where} ORDER BY {spec['date_col']} DESC",
        (uid, dt_from, dt_to),
    ).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        cells = []
        for c, _ in spec["cols"]:
            v = d[c]
            if v is None or v == "":
                v = "-"
            elif c in AMT_COLS:
                v = f"{v:,.0f}"
            elif c in CODE_COLS:
                v = CODE_LABELS.get(v, v)
            cells.append({"v": v, "num": c in AMT_COLS or c.endswith("_qty")})
        out.append({"id": d["id"], "cells": cells})

    return {
        "label": spec["label"],
        "count": len(rows),
        "rows": out,
        "heads": [h for _, h in spec["cols"]],
        "link": spec["link"],
    }


def sync_erp_volume(conn, task):
    result = get_erp_deliverables(conn, task)
    if result is None:
        return
    cnt = result["count"]
    if cnt != (task.get("completed_volume") or 0):
        conn.execute("UPDATE tasks SET completed_volume=? WHERE id=?", (cnt, task["id"]))

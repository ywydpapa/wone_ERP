import csv
import io
import json

from core.export import esc_cell

EXPORT_KEY = {
    "slip_purchase": "slip", "slip_sales": "slip", "slip_expense": "slip",
    "po_entry": "po", "gr_entry": "gr", "pr_entry": "pr",
    "quote_entry": "quote", "so_entry": "so", "ship_entry": "ship",
    "wo_entry": "wo", "bom_entry": "bom",
    "item_entry": "item", "partner_entry": "partner",
}

EXPORT_SCHEMAS = {
    "slip": {
        "label": "전표",
        "columns": [("slip_date", "전표일자"), ("slip_type", "전표유형"),
                    ("account_code", "계정코드"), ("account_name", "계정과목"),
                    ("partner", "거래처"), ("debit", "차변"), ("credit", "대변"),
                    ("summary", "적요"), ("writer", "입력자"), ("created_at", "입력일시")],
        "number_cols": {"debit", "credit"},
        "sql": """SELECT d.slip_date, d.slip_type, l.account_code, l.account_name,
                         l.partner, l.debit, l.credit, l.summary,
                         u.name AS writer, d.created_at
                  FROM erp_docs d
                  JOIN slip_lines l ON l.doc_id = d.id
                  JOIN users u ON u.id = d.user_id
                  WHERE d.task_id IN ({ph})
                  ORDER BY d.slip_date, d.id, l.line_no""",
    },
    "po": {
        "label": "발주",
        "columns": [("po_number", "발주번호"), ("po_date", "발주일"),
                    ("delivery_date", "납기일"), ("partner", "거래처"),
                    ("item_code", "품목코드"), ("item_name", "품목명"),
                    ("quantity", "수량"), ("unit_price", "단가"), ("amount", "금액"),
                    ("status", "상태"), ("writer", "입력자"), ("created_at", "입력일시")],
        "number_cols": {"quantity", "unit_price", "amount"},
        "sql": """SELECT po.po_number, po.po_date, po.delivery_date, pt.name AS partner,
                         i.item_code, i.item_name, l.quantity, l.unit_price, l.amount,
                         po.status, u.name AS writer, po.created_at
                  FROM purchase_orders po
                  JOIN po_lines l ON l.po_id = po.id
                  JOIN items i ON i.id = l.item_id
                  LEFT JOIN partners pt ON pt.id = po.partner_id
                  LEFT JOIN users u ON u.id = po.created_by
                  WHERE po.task_id IN ({ph})
                  ORDER BY po.po_date, po.id, l.line_no""",
    },
    "gr": {
        "label": "입고",
        "columns": [("gr_number", "입고번호"), ("receipt_date", "입고일"),
                    ("po_number", "발주번호"), ("item_code", "품목코드"),
                    ("item_name", "품목명"), ("received_qty", "입고수량"),
                    ("defective_qty", "불량수량"), ("status", "상태"),
                    ("writer", "입력자"), ("created_at", "입력일시")],
        "number_cols": {"received_qty", "defective_qty"},
        "sql": """SELECT g.gr_number, g.receipt_date, po.po_number,
                         i.item_code, i.item_name, l.received_qty, l.defective_qty,
                         g.status, u.name AS writer, g.created_at
                  FROM goods_receipts g
                  JOIN gr_lines l ON l.gr_id = g.id
                  JOIN items i ON i.id = l.item_id
                  LEFT JOIN purchase_orders po ON po.id = g.po_id
                  LEFT JOIN users u ON u.id = g.created_by
                  WHERE g.task_id IN ({ph})
                  ORDER BY g.receipt_date, g.id""",
    },
    "pr": {
        "label": "구매요청",
        "columns": [("pr_number", "요청번호"), ("request_date", "요청일"),
                    ("need_date", "필요일"), ("dept", "부서"), ("item_name", "품목명"),
                    ("quantity", "수량"), ("estimated_price", "예상단가"),
                    ("status", "상태"), ("writer", "입력자"), ("created_at", "입력일시")],
        "number_cols": {"quantity", "estimated_price"},
        "sql": """SELECT p.pr_number, p.request_date, p.need_date, p.dept,
                         l.item_name, l.quantity, l.estimated_price,
                         p.status, u.name AS writer, p.created_at
                  FROM purchase_requisitions p
                  JOIN pr_lines l ON l.pr_id = p.id
                  LEFT JOIN users u ON u.id = p.requester_id
                  WHERE p.task_id IN ({ph})
                  ORDER BY p.request_date, p.id, l.line_no""",
    },
    "quote": {
        "label": "견적",
        "columns": [("quote_number", "견적번호"), ("quote_date", "견적일"),
                    ("valid_until", "유효기한"), ("customer", "고객사"),
                    ("item_code", "품목코드"), ("item_name", "품목명"),
                    ("quantity", "수량"), ("unit_price", "단가"), ("amount", "금액"),
                    ("status", "상태"), ("writer", "입력자"), ("created_at", "입력일시")],
        "number_cols": {"quantity", "unit_price", "amount"},
        "sql": """SELECT q.quote_number, q.quote_date, q.valid_until, c.name AS customer,
                         i.item_code, i.item_name, l.quantity, l.unit_price, l.amount,
                         q.status, u.name AS writer, q.created_at
                  FROM quotations q
                  JOIN quote_lines l ON l.quote_id = q.id
                  JOIN items i ON i.id = l.item_id
                  LEFT JOIN client_companies c ON c.id = q.customer_id
                  LEFT JOIN users u ON u.id = q.created_by
                  WHERE q.task_id IN ({ph})
                  ORDER BY q.quote_date, q.id, l.line_no""",
    },
    "so": {
        "label": "수주",
        "columns": [("so_number", "수주번호"), ("order_date", "수주일"),
                    ("delivery_date", "납기일"), ("customer", "고객사"),
                    ("item_code", "품목코드"), ("item_name", "품목명"),
                    ("quantity", "수량"), ("unit_price", "단가"), ("amount", "금액"),
                    ("status", "상태"), ("writer", "입력자"), ("created_at", "입력일시")],
        "number_cols": {"quantity", "unit_price", "amount"},
        "sql": """SELECT s.so_number, s.order_date, s.delivery_date, c.name AS customer,
                         i.item_code, i.item_name, l.quantity, l.unit_price, l.amount,
                         s.status, u.name AS writer, s.created_at
                  FROM sales_orders s
                  JOIN so_lines l ON l.so_id = s.id
                  JOIN items i ON i.id = l.item_id
                  LEFT JOIN client_companies c ON c.id = s.customer_id
                  LEFT JOIN users u ON u.id = s.created_by
                  WHERE s.task_id IN ({ph})
                  ORDER BY s.order_date, s.id, l.line_no""",
    },
    "ship": {
        "label": "출하",
        "columns": [("ship_number", "출하번호"), ("ship_date", "출하일"),
                    ("so_number", "수주번호"), ("item_code", "품목코드"),
                    ("item_name", "품목명"), ("shipped_qty", "출하수량"),
                    ("status", "상태"), ("writer", "입력자"), ("created_at", "입력일시")],
        "number_cols": {"shipped_qty"},
        "sql": """SELECT sh.ship_number, sh.ship_date, so.so_number,
                         i.item_code, i.item_name, l.shipped_qty,
                         sh.status, u.name AS writer, sh.created_at
                  FROM shipments sh
                  JOIN ship_lines l ON l.ship_id = sh.id
                  JOIN items i ON i.id = l.item_id
                  LEFT JOIN sales_orders so ON so.id = sh.so_id
                  LEFT JOIN users u ON u.id = sh.created_by
                  WHERE sh.task_id IN ({ph})
                  ORDER BY sh.ship_date, sh.id""",
    },
    "wo": {
        "label": "작업지시",
        "columns": [("wo_number", "지시번호"), ("item_code", "품목코드"),
                    ("item_name", "품목명"), ("planned_qty", "계획수량"),
                    ("actual_qty", "실적수량"), ("planned_start", "계획시작"),
                    ("planned_end", "계획종료"), ("status", "상태"),
                    ("writer", "입력자"), ("created_at", "입력일시")],
        "number_cols": {"planned_qty", "actual_qty"},
        "sql": """SELECT w.wo_number, i.item_code, i.item_name, w.planned_qty,
                         w.actual_qty, w.planned_start, w.planned_end,
                         w.status, u.name AS writer, w.created_at
                  FROM work_orders w
                  JOIN items i ON i.id = w.product_id
                  LEFT JOIN users u ON u.id = w.created_by
                  WHERE w.task_id IN ({ph})
                  ORDER BY w.id""",
    },
    "bom": {
        "label": "BOM",
        "columns": [("product_code", "제품코드"), ("product_name", "제품명"),
                    ("bom_version", "버전"), ("comp_code", "자재코드"),
                    ("comp_name", "자재명"), ("quantity", "소요량"),
                    ("unit", "단위"), ("process_step", "공정"), ("created_at", "입력일시")],
        "number_cols": {"quantity"},
        "sql": """SELECT p.item_code AS product_code, p.item_name AS product_name,
                         b.bom_version, c.item_code AS comp_code, c.item_name AS comp_name,
                         l.quantity, l.unit, l.process_step, b.created_at
                  FROM bom_headers b
                  JOIN items p ON p.id = b.product_id
                  JOIN bom_lines l ON l.bom_id = b.id
                  JOIN items c ON c.id = l.component_id
                  WHERE b.task_id IN ({ph})
                  ORDER BY b.id, l.id""",
    },
    "item": {
        "label": "품목",
        "columns": [("item_code", "품목코드"), ("item_name", "품목명"),
                    ("item_type", "품목유형"), ("unit", "단위"),
                    ("unit_price", "단가"), ("category", "분류"), ("created_at", "입력일시")],
        "number_cols": {"unit_price"},
        "sql": """SELECT i.item_code, i.item_name, i.item_type, i.unit,
                         i.unit_price, i.category, i.created_at
                  FROM items i WHERE i.task_id IN ({ph}) ORDER BY i.item_code""",
    },
    "partner": {
        "label": "거래처",
        "columns": [("code", "거래처코드"), ("name", "거래처명"),
                    ("biz_no", "사업자번호"), ("representative", "대표자"),
                    ("biz_type", "업태"), ("biz_item", "종목"),
                    ("phone", "전화"), ("address", "주소")],
        "number_cols": set(),
        "sql": """SELECT p.code, p.name, p.biz_no, p.representative,
                         p.biz_type, p.biz_item, p.phone, p.address
                  FROM partners p WHERE p.task_id IN ({ph}) ORDER BY p.code""",
    },
}


def fetch_rows(conn, key, task_ids):
    schema = EXPORT_SCHEMAS[key]
    ph = ",".join("?" * len(task_ids))
    rows = conn.execute(schema["sql"].format(ph=ph), task_ids).fetchall()
    return [dict(r) for r in rows]


def std_lines(key, rows):
    schema = EXPORT_SCHEMAS[key]
    headers = [h for _, h in schema["columns"]]
    lines = [[r.get(src, "") for src, _ in schema["columns"]] for r in rows]
    return headers, lines


def apply_template(key, tpl_row, rows):
    schema = EXPORT_SCHEMAS[key]
    std = dict(schema["columns"])
    cols = json.loads(tpl_row["columns"])
    headers = [c.get("header") or std.get(c["src"], c["src"]) for c in cols]
    lines = []
    for r in rows:
        line = []
        for c in cols:
            v = r.get(c["src"], "")
            fmt = c.get("fmt", "")
            if fmt == "ymd" and isinstance(v, str):
                v = v.replace("-", "")
            elif fmt == "comma" and isinstance(v, int):
                v = format(v, ",")
            line.append(v)
        lines.append(line)
    return headers, lines


def csv_bytes(headers, lines):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for line in lines:
        w.writerow([esc_cell(v) for v in line])
    return buf.getvalue().encode("utf-8-sig")


def dummy_rows(key):
    # 템플릿 미리보기용. 실데이터 대신 더미만 사용 (staff는 실데이터 접근 불가)
    schema = EXPORT_SCHEMAS[key]
    row = {}
    for src, _ in schema["columns"]:
        if src in schema["number_cols"]:
            row[src] = 150000
        elif "date" in src or src in ("created_at", "valid_until", "planned_start", "planned_end"):
            row[src] = "2026-01-15"
        else:
            row[src] = "샘플"
    return [row]

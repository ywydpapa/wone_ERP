import csv
import io
import json

from core.export import esc_cell
from core.invoices import vat_code

EXPORT_KEY = {
    "slip_purchase": "slip", "slip_sales": "slip", "slip_expense": "slip",
    "po_entry": "po", "gr_entry": "gr", "pr_entry": "pr",
    "quote_entry": "quote", "so_entry": "so", "ship_entry": "ship",
    "wo_entry": "wo", "bom_entry": "bom",
    "item_entry": "item", "partner_entry": "partner",
}


def fill_vat(r):
    r["vat_type"] = vat_code(r)[:2]
    r["year"], r["month"], r["day"] = (int(v) for v in r["issue_date"].split("-"))
    r["kind_cd"] = 1 if r["kind"] == "매출" else 2
    r["elec"] = "전자" if r["is_electronic"] else ""
    r["elec_cd"] = 1 if r["is_electronic"] else ""
    r["cash_appr"] = r["approval_no"] if r["evidence"] == "현금영수증" else ""
    r["card_no"] = (r["card_no"] or "") if r["evidence"] == "카드" else ""
    if r["nondeduct_reason"] is None:
        r["nondeduct_reason"] = ""


EXPORT_SCHEMAS = {
    "slip": {
        "label": "전표",
        "columns": [("slip_no", "전표번호"), ("slip_date", "전표일자"), ("slip_type", "전표유형"),
                    ("line_no", "라인순번"), ("account_code", "계정코드"), ("account_name", "계정과목"),
                    ("partner_code", "거래처코드"), ("partner", "거래처"), ("biz_no", "사업자번호"),
                    ("debit", "차변"), ("credit", "대변"), ("summary", "적요"),
                    ("dept", "부서"), ("project_code", "프로젝트"),
                    ("evidence_type", "증빙유형"), ("evidence_no", "증빙번호"),
                    ("writer", "입력자"), ("created_at", "입력일시")],
        # 템플릿 전용 계산 컬럼. 표준 반출 제외
        "derived": [("day_seq", "일자별 전표순번"), ("dc_type", "차대구분"), ("dc_amt", "차대 금액")],
        "number_cols": {"debit", "credit"},
        "sql": """SELECT d.id AS doc_id, d.slip_no, d.slip_date, d.slip_type, l.line_no,
                         l.account_code, l.account_name, pt.code AS partner_code, l.partner, pt.biz_no,
                         l.debit, l.credit, l.summary, l.dept, l.project_code,
                         d.evidence_type, d.evidence_no, u.name AS writer, d.created_at
                  FROM erp_docs d
                  JOIN slip_lines l ON l.doc_id = d.id
                  JOIN users u ON u.id = d.user_id
                  LEFT JOIN partners pt ON pt.id = l.partner_id
                  WHERE d.task_id IN ({ph})
                  ORDER BY d.slip_date, d.id, l.line_no""",
    },
    # 증빙 1건이 1행. 기본계정은 부가세 계정 제외 첫 라인, 상대계정은 반대편 첫 라인 기준
    "vat": {
        "label": "매입매출",
        "columns": [("slip_no", "전표번호"), ("issue_date", "작성일자"), ("kind", "매입매출구분"),
                    ("vat_type", "과세유형"), ("evidence", "증빙"), ("nondeduct_reason", "불공제사유"),
                    ("partner_code", "거래처코드"), ("partner", "거래처"), ("biz_no", "사업자번호"),
                    ("supply_amt", "공급가액"), ("vat", "부가세"), ("total", "합계"), ("item", "품명"),
                    ("elec", "전자"), ("approval_no", "승인번호"),
                    ("base_acct", "기본계정"), ("contra_acct", "상대계정"),
                    ("remark", "비고"), ("status", "상태")],
        "derived": [("year", "년도"), ("month", "월"), ("day", "일"), ("kind_cd", "매입매출구분 코드"),
                    ("elec_cd", "전자 코드"), ("cash_appr", "현금영수증 승인번호"),
                    ("card_no", "카드번호")],
        "number_cols": {"supply_amt", "vat", "total"},
        "sql": """SELECT d.id AS doc_id, d.slip_no, t.issue_date, t.kind, t.tax_type, t.evidence, t.deduct,
                         t.nondeduct_reason, pt.code AS partner_code, pt.name AS partner, pt.biz_no,
                         t.supply_amt, t.vat, t.total, t.is_electronic, t.approval_no, t.remark, t.status,
                         (SELECT name FROM tax_invoice_items
                          WHERE invoice_id = t.id ORDER BY line_no LIMIT 1) AS item,
                         (SELECT account_code FROM slip_lines
                          WHERE doc_id = d.id AND account_code NOT IN ('135', '255')
                            AND CASE t.kind WHEN '매입' THEN debit ELSE credit END > 0
                          ORDER BY line_no LIMIT 1) AS base_acct,
                         (SELECT account_code FROM slip_lines
                          WHERE doc_id = d.id AND CASE t.kind WHEN '매입' THEN credit ELSE debit END > 0
                          ORDER BY line_no LIMIT 1) AS contra_acct,
                         (SELECT card_no FROM card_txns WHERE tax_invoice_id = t.id LIMIT 1) AS card_no
                  FROM tax_invoices t
                  JOIN erp_docs d ON d.id = t.doc_id
                  LEFT JOIN partners pt ON pt.id = t.partner_id
                  WHERE d.task_id IN ({ph})
                  ORDER BY t.issue_date, t.id""",
        "fill": fill_vat,
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
                  LEFT JOIN partners c ON c.id = q.partner_id
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
                  LEFT JOIN partners c ON c.id = s.partner_id
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
                    ("phone", "전화"), ("fax", "팩스"), ("email", "이메일"), ("address", "주소")],
        "number_cols": set(),
        "sql": """SELECT p.code, p.name, p.biz_no, p.representative,
                         p.biz_type, p.biz_item, p.phone, p.fax, p.email, p.address
                  FROM partners p WHERE p.task_id IN ({ph}) ORDER BY p.code""",
    },
}


def fetch_rows(conn, key, task_ids):
    schema = EXPORT_SCHEMAS[key]
    ph = ",".join("?" * len(task_ids))
    rows = [dict(r) for r in conn.execute(schema["sql"].format(ph=ph), task_ids).fetchall()]
    if "fill" in schema:
        for r in rows:
            schema["fill"](r)
    return rows


def std_lines(key, rows):
    schema = EXPORT_SCHEMAS[key]
    headers = [h for _, h in schema["columns"]]
    lines = [[r.get(src, "") for src, _ in schema["columns"]] for r in rows]
    return headers, lines


# 업체 양식 초안. 고정값 중 input 지정 컬럼은 고객사 입력값으로 채움
# 양식 미확보 업체는 modules를 비워 두고 표준 양식으로 반출
PRESETS = {
    "douzone_icube": {
        "label": "더존 iCUBE",
        "name": "더존 iCUBE",
        "note": "일반전표는 유상 메뉴(자동전표처리 간소화) 양식 기준. 계정코드는 우리 코드 그대로 반출",
        "inputs": [("co_cd", "회사코드"), ("div_cd", "회계단위")],
        "modules": {
            "slip": [
                {"src": "_fixed", "header": "회사코드", "value": "", "input": "co_cd"},
                {"src": "slip_date", "header": "거래일자", "fmt": "ymd"},
                {"src": "day_seq", "header": "거래순번"},
                {"src": "line_no", "header": "분개라인순번"},
                {"src": "_fixed", "header": "회계단위", "value": "", "input": "div_cd"},
                {"src": "dc_type", "header": "차대구분", "codes": ["3", "4"]},
                {"src": "account_code", "header": "계정코드"},
                {"src": "biz_no", "header": "거래처사업자번호", "fmt": "ymd"},
                {"src": "dc_amt", "header": "금액"},
                {"src": "summary", "header": "적요"},
            ],
        },
    },
    "douzone_smarta": {
        "label": "더존 Smart A",
        "name": "더존 Smart A",
        "note": "매입매출전표 엑셀업로드 원본 양식 기준. 계정코드는 원본 예시대로 뒤에 00을 붙여 반출. "
                "일반전표는 업로드 메뉴가 없으므로 표준 양식으로 반출. 카드사 정보는 카드 증빙 행에만 기재",
        "inputs": [("card_cd", "카드사 거래처코드"), ("card_name", "카드사명")],
        "modules": {
            "vat": [
                {"src": "year", "header": "년도"},
                {"src": "month", "header": "월"},
                {"src": "day", "header": "일"},
                {"src": "kind_cd", "header": "매입매출구분(1-매출/2-매입)"},
                {"src": "vat_type", "header": "과세유형"},
                {"src": "nondeduct_reason", "header": "불공제사유"},
                {"src": "_fixed", "header": "신용카드거래처코드", "value": "", "input": "card_cd", "card": True},
                {"src": "_fixed", "header": "신용카드사명", "value": "", "input": "card_name", "card": True},
                {"src": "card_no", "header": "신용카드(가맹점)번호"},
                {"src": "partner", "header": "거래처명"},
                {"src": "biz_no", "header": "사업자(주민)등록번호"},
                {"src": "supply_amt", "header": "공급가액"},
                {"src": "vat", "header": "부가세"},
                {"src": "item", "header": "품명"},
                {"src": "elec_cd", "header": "전자세금(1.전자)"},
                {"src": "base_acct", "header": "기본계정", "fmt": "acct5"},
                {"src": "contra_acct", "header": "상대계정", "fmt": "acct5"},
                {"src": "cash_appr", "header": "현금영수증 승인번호"},
            ],
        },
    },
    "ecount": {
        "label": "이카운트",
        "name": "이카운트",
        "note": "거래처 웹자료올리기 양식 기준. 그 외 모듈은 표준 양식으로 반출",
        "inputs": [],
        "modules": {
            "partner": [
                {"src": "code", "header": "거래처코드"},
                {"src": "name", "header": "상호"},
                {"src": "representative", "header": "대표자명"},
                {"src": "biz_type", "header": "업태"},
                {"src": "biz_item", "header": "종목"},
                {"src": "phone", "header": "전화"},
                {"src": "fax", "header": "팩스"},
                {"src": "email", "header": "이메일"},
                {"src": "_fixed", "header": "검색창내용", "value": ""},
                {"src": "_fixed", "header": "우편번호", "value": ""},
                {"src": "address", "header": "주소"},
            ],
        },
    },
}


def apply_preset(conn, company_id, key, vals, uid):
    # 기존 양식은 입력값 컬럼만 갱신. 플랫폼 담당자 수정분 보존
    p = PRESETS[key]
    for module, base in p["modules"].items():
        row = conn.execute(
            "SELECT id, columns FROM export_templates WHERE company_id = ? AND module = ? AND name = ?",
            (company_id, module, p["name"])).fetchone()
        cols = json.loads(row["columns"]) if row else [dict(c) for c in base]
        for c in cols:
            if c.get("input") in vals:
                c["value"] = vals[c["input"]]
        data = json.dumps(cols, ensure_ascii=False)
        if row:
            conn.execute("UPDATE export_templates SET columns = ?, updated_at = datetime('now','localtime') "
                         "WHERE id = ?", (data, row["id"]))
        else:
            conn.execute("INSERT INTO export_templates (company_id, module, name, columns, created_by) "
                         "VALUES (?, ?, ?, ?, ?)", (company_id, module, p["name"], data, uid))


def preset_vals(conn, company_id, key):
    p = PRESETS[key]
    vals = {k: "" for k, _ in p["inputs"]}
    for r in conn.execute("SELECT columns FROM export_templates WHERE company_id = ? AND name = ?",
                          (company_id, p["name"])).fetchall():
        for c in json.loads(r["columns"]):
            if c.get("input") in vals:
                vals[c["input"]] = c.get("value", "")
    return vals


def day_seqs(rows):
    # 같은 일자 안에서 전표 단위 순번. 라인은 소속 전표 순번 공유
    seqs, cnt = {}, {}
    for r in rows:
        if r["doc_id"] not in seqs:
            cnt[r["slip_date"]] = cnt.get(r["slip_date"], 0) + 1
            seqs[r["doc_id"]] = cnt[r["slip_date"]]
    return seqs


def apply_template(key, tpl_row, rows):
    schema = EXPORT_SCHEMAS[key]
    std = dict(schema["columns"] + schema.get("derived", []))
    cols = json.loads(tpl_row["columns"])
    headers = [c.get("header") or std.get(c["src"], c["src"]) for c in cols]
    seqs = day_seqs(rows) if any(c["src"] == "day_seq" for c in cols) else {}
    lines = []
    for r in rows:
        line = []
        for c in cols:
            src = c["src"]
            if src == "_fixed":
                v = "" if c.get("card") and r.get("evidence") != "카드" else c.get("value", "")
            elif src == "day_seq":
                v = seqs[r["doc_id"]]
            elif src == "dc_type":
                dr, cr = c.get("codes") or ["차변", "대변"]
                v = dr if r["debit"] else cr
            elif src == "dc_amt":
                v = r["debit"] or r["credit"]
            else:
                v = r.get(src, "")
            fmt = c.get("fmt", "")
            if fmt == "ymd" and isinstance(v, str):
                v = v.replace("-", "")
            elif fmt == "comma" and isinstance(v, int):
                v = format(v, ",")
            elif fmt == "acct5" and v:
                v = f"{v}00"
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
    row = {"doc_id": 1}
    for src, _ in schema["columns"]:
        if src in schema["number_cols"]:
            row[src] = 150000
        elif "date" in src or src in ("created_at", "valid_until", "planned_start", "planned_end"):
            row[src] = "2026-01-15"
        else:
            row[src] = "샘플"
    return [row]

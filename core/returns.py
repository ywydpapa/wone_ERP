from core import audit, books, invoices, stock
from core.tz import now_kst

# 입고 반품은 발주(po), 출고 반품은 수주(so) 라인의 returned_qty 가산
DOCS = {
    "gr": {"head": "goods_receipts", "lines": "gr_lines", "fk": "gr_id", "qty": "received_qty",
           "no": "gr_number", "date": "receipt_date", "kind": "입고", "src": "gr", "label": "구매 반품"},
    "ship": {"head": "shipments", "lines": "ship_lines", "fk": "ship_id", "qty": "shipped_qty",
             "no": "ship_number", "date": "ship_date", "kind": "출고", "src": "ship", "label": "판매 반품"},
}


def _orig(conn, book, typ, orig_id):
    d = DOCS[typ]
    head = conn.execute(f"SELECT * FROM {d['head']} WHERE id=? AND company_id=? AND kind=? AND status='confirmed'",
                        (orig_id, book, d["kind"])).fetchone()
    if not head:
        raise LookupError
    return head


# 원 라인별 반품 가능 수량. 입고는 불량 제외 양품 수량 기준
def limits(conn, book, typ, orig_id):
    d = DOCS[typ]
    _orig(conn, book, typ, orig_id)
    good = f"l.{d['qty']} - l.defective_qty" if typ == "gr" else f"l.{d['qty']}"
    return {r["id"]: r["qty"] - r["done"] for r in conn.execute(
        f"""SELECT l.id, {good} AS qty,
                   COALESCE((SELECT SUM(r.{d['qty']}) FROM {d['lines']} r JOIN {d['head']} h ON h.id=r.{d['fk']}
                             WHERE r.orig_line_id=l.id AND h.canceled_at IS NULL), 0) AS done
            FROM {d['lines']} l WHERE l.{d['fk']}=?""", (orig_id,))}


def _orig_invoice(conn, book, typ, orig_id):
    return conn.execute("SELECT * FROM tax_invoices WHERE company_id=? AND source_type=? AND source_id=? "
                        "AND status='정상'", (book, typ, orig_id)).fetchone()


def _sync_order(conn, typ, order_id):
    if typ == "gr":
        left = conn.execute("SELECT COUNT(*) FROM po_lines WHERE po_id=? AND quantity > received_qty - returned_qty",
                            (order_id,)).fetchone()[0]
        conn.execute("UPDATE purchase_orders SET status=? WHERE id=? AND status IN ('partial','completed')",
                     ("partial" if left else "completed", order_id))
    else:
        left = conn.execute("SELECT COUNT(*) FROM so_lines WHERE so_id=? AND quantity > shipped_qty - returned_qty",
                            (order_id,)).fetchone()[0]
        conn.execute("UPDATE sales_orders SET status=? WHERE id=? AND status IN ('picking','shipped')",
                     ("picking" if left else "shipped", order_id))


# qtys {원 라인 id: 반품 수량}. number는 라우터 채번 결과
def create(conn, book, uid, typ, orig_id, ret_date, qtys, notes, number):
    d = DOCS[typ]
    head = _orig(conn, book, typ, orig_id)
    order_id = head["po_id"] if typ == "gr" else head["so_id"]
    if not order_id:
        raise ValueError("발주/수주와 연결된 문서만 반품할 수 있습니다.")
    cap = limits(conn, book, typ, orig_id)
    qtys = {lid: q for lid, q in qtys.items() if q}
    if not qtys:
        raise ValueError("반품 수량을 입력해 주세요.")
    for lid, q in qtys.items():
        if lid not in cap:
            raise LookupError
        if q < 0 or q > cap[lid]:
            raise ValueError("반품 가능 수량을 초과했습니다.")

    if typ == "gr":
        partner_id = conn.execute("SELECT partner_id FROM purchase_orders WHERE id=?", (order_id,)).fetchone()[0]
        ret_id = conn.execute(
            """INSERT INTO goods_receipts (gr_number, po_id, warehouse_id, receipt_date, status, notes, created_by,
                   company_id, kind) VALUES (?,?,?,?,'confirmed',?,?,?,'반품')""",
            (number, order_id, head["warehouse_id"], ret_date, notes, uid, book)).lastrowid
    else:
        partner_id = conn.execute("SELECT partner_id FROM sales_orders WHERE id=?", (order_id,)).fetchone()[0]
        ret_id = conn.execute(
            """INSERT INTO shipments (ship_number, so_id, warehouse_id, ship_date, status, notes, created_by,
                   company_id, kind, contact_id, ship_to) VALUES (?,?,?,?,'confirmed',?,?,?,'반품',?,?)""",
            (number, order_id, head["warehouse_id"], ret_date, notes, uid, book, head["contact_id"],
             head["ship_to"])).lastrowid

    amount = cogs = 0
    for lid, q in qtys.items():
        ol = conn.execute(f"SELECT * FROM {d['lines']} WHERE id=?", (lid,)).fetchone()
        if typ == "gr":
            conn.execute("""INSERT INTO gr_lines (gr_id, po_line_id, item_id, received_qty, defective_qty, orig_line_id)
                            VALUES (?,?,?,?,0,?)""", (ret_id, ol["po_line_id"], ol["item_id"], q, lid))
            stock.move_out(conn, ol["item_id"], head["warehouse_id"], q, ret_date, "gr", ret_id, uid)
            price = conn.execute("SELECT COALESCE(MAX(unit_price), 0) FROM po_lines WHERE id=?",
                                 (ol["po_line_id"],)).fetchone()[0]
            conn.execute("UPDATE po_lines SET returned_qty = returned_qty + ? WHERE id=?", (q, ol["po_line_id"]))
        else:
            conn.execute("""INSERT INTO ship_lines (ship_id, so_line_id, item_id, shipped_qty, orig_line_id)
                            VALUES (?,?,?,?,?)""", (ret_id, ol["so_line_id"], ol["item_id"], q, lid))
            # 원 출고 시점 원가 단가로 재입고
            out = conn.execute("""SELECT SUM(amount), SUM(quantity) FROM stock_transactions
                                  WHERE ref_type='ship' AND ref_id=? AND item_id=? AND trans_type='out'""",
                               (orig_id, ol["item_id"])).fetchone()
            cogs += stock.move_in(conn, ol["item_id"], head["warehouse_id"], q, ret_date, "ship", ret_id, uid,
                                  out[0] / out[1] if out[1] else 0)
            price = conn.execute("SELECT COALESCE(MAX(unit_price), 0) FROM so_lines WHERE id=?",
                                 (ol["so_line_id"],)).fetchone()[0]
            conn.execute("UPDATE so_lines SET returned_qty = returned_qty + ? WHERE id=?", (q, ol["so_line_id"]))
        amount += round(q * price)
    _sync_order(conn, typ, order_id)

    inv = _orig_invoice(conn, book, typ, orig_id)
    vat = invoices.calc_vat(amount) if inv and inv["tax_type"] == "과세" else 0
    neg = {"kind": "매입" if typ == "gr" else "매출", "partner_id": partner_id, "supply_amt": -amount, "vat": -vat,
           "deduct": inv["deduct"] if inv else 1}
    summary = f"{d['label']} {number}"
    lines = invoices.inv_lines(neg, "120", "251", summary) if typ == "gr" else invoices.inv_lines(neg, "401", "110", summary)
    if cogs:
        lines += [{"code": "120", "debit": cogs, "credit": 0, "summary": summary},
                  {"code": "451", "debit": 0, "credit": cogs, "summary": summary}]
    if lines:
        doc_id = books.post(conn, book, uid, ret_date, lines, f"{d['label']} 전표 ({number})", f"{typ}_return", ret_id)
        # 원 세금계산서 기준 환입 수정분. 별도 전표 없이 반품 전표에 연결
        if inv and amount:
            cur = conn.execute("SELECT SUM(supply_amt) FROM tax_invoices WHERE id=? OR orig_id=?",
                               (inv["id"], inv["id"])).fetchone()[0]
            invoices.add(conn, book, uid, {
                **dict(inv), "issue_date": ret_date, "supply_amt": -amount, "vat": -vat,
                "status": "취소" if cur - amount <= 0 else "수정", "orig_id": inv["id"], "approval_no": "",
                "source_type": "amend", "source_id": inv["id"], "amend_reason": 3, "doc_id": doc_id})
    audit.log(conn, uid, f"{typ}_return", "gr" if typ == "gr" else "shipment", ret_id,
              f"{number} {amount:,}", company_id=book)
    return ret_id


def cancel(conn, book, uid, typ, ret_id):
    d = DOCS[typ]
    head = conn.execute(f"SELECT * FROM {d['head']} WHERE id=? AND company_id=? AND kind='반품'",
                        (ret_id, book)).fetchone()
    if not head:
        raise LookupError
    if head["canceled_at"]:
        raise ValueError("이미 취소된 반품입니다.")
    for doc in conn.execute("SELECT id FROM erp_docs WHERE company_id=? AND source_type=? AND source_id=? "
                            "AND reversal_of IS NULL", (book, f"{typ}_return", ret_id)).fetchall():
        books.reverse(conn, doc["id"], uid, head[d["date"]])
        inv_ids = [r[0] for r in conn.execute("SELECT id FROM tax_invoices WHERE doc_id=? AND source_type='amend'",
                                              (doc["id"],))]
        for iid in inv_ids:
            conn.execute("DELETE FROM tax_invoice_items WHERE invoice_id=?", (iid,))
            conn.execute("DELETE FROM tax_invoices WHERE id=?", (iid,))

    for ln in conn.execute(f"SELECT * FROM {d['lines']} WHERE {d['fk']}=?", (ret_id,)).fetchall():
        q = ln[d["qty"]]
        if typ == "gr":
            moved = conn.execute("""SELECT SUM(amount), SUM(quantity) FROM stock_transactions WHERE ref_type='gr'
                                    AND ref_id=? AND item_id=? AND trans_type='out'""", (ret_id, ln["item_id"])).fetchone()
            stock.move_in(conn, ln["item_id"], head["warehouse_id"], q, head[d["date"]], "gr", ret_id, uid,
                          moved[0] / moved[1])
            conn.execute("UPDATE po_lines SET returned_qty = returned_qty - ? WHERE id=?", (q, ln["po_line_id"]))
        else:
            stock.move_out(conn, ln["item_id"], head["warehouse_id"], q, head[d["date"]], "ship", ret_id, uid)
            conn.execute("UPDATE so_lines SET returned_qty = returned_qty - ? WHERE id=?", (q, ln["so_line_id"]))
    _sync_order(conn, typ, head["po_id"] if typ == "gr" else head["so_id"])
    conn.execute(f"UPDATE {d['head']} SET canceled_at=? WHERE id=?",
                 (now_kst().strftime("%Y-%m-%d %H:%M:%S"), ret_id))
    audit.log(conn, uid, "return_cancel", "gr" if typ == "gr" else "shipment", ret_id,
              f"{head[d['no']]} 반품 취소", company_id=book)

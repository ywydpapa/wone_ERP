# 재고 입출고 단일 지점. 원가는 이동평균, 품목 단위(창고 무관)로 items.stock_amt에 보유


def _total(conn, item_id):
    return conn.execute("SELECT COALESCE(SUM(quantity), 0) FROM stock WHERE item_id=?", (item_id,)).fetchone()[0]


def _log(conn, item_id, wh_id, kind, qty, amt, date, ref, ref_id, uid):
    bal = conn.execute(
        "SELECT quantity FROM stock WHERE item_id=? AND warehouse_id=?", (item_id, wh_id)
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO stock_transactions (item_id, warehouse_id, trans_date, trans_type, quantity,
               ref_type, ref_id, balance_qty, amount, created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (item_id, wh_id, date, kind, qty, ref, ref_id, bal, amt, uid),
    )


def move_in(conn, item_id, wh_id, qty, date, ref, ref_id, uid, price=None):
    # 단가 없는 입고(무발주, 생산)는 현재 평균단가로 처리
    if price is None:
        total = _total(conn, item_id)
        stock_amt = conn.execute("SELECT stock_amt FROM items WHERE id=?", (item_id,)).fetchone()[0]
        amt = round(stock_amt * qty / total) if total > 0 else 0
    else:
        amt = round(qty * price)
    conn.execute(
        """INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,?)
           ON CONFLICT(item_id, warehouse_id) DO UPDATE SET quantity = quantity + excluded.quantity""",
        (item_id, wh_id, qty),
    )
    conn.execute("UPDATE items SET stock_amt = stock_amt + ? WHERE id=?", (amt, item_id))
    _log(conn, item_id, wh_id, "in", qty, amt, date, ref, ref_id, uid)
    return amt


def move_out(conn, item_id, wh_id, qty, date, ref, ref_id, uid):
    # 조건부 차감으로 동시 출고 시에도 음수 불가
    cur = conn.execute(
        "UPDATE stock SET quantity = quantity - ? WHERE item_id=? AND warehouse_id=? AND quantity >= ?",
        (qty, item_id, wh_id, qty),
    )
    if not cur.rowcount:
        row = conn.execute(
            "SELECT quantity FROM stock WHERE item_id=? AND warehouse_id=?", (item_id, wh_id)
        ).fetchone()
        name = conn.execute("SELECT item_name FROM items WHERE id=?", (item_id,)).fetchone()[0]
        raise ValueError(f"재고 부족: {name} (재고 {row[0] if row else 0}, 출고 {qty})")
    left = _total(conn, item_id)
    stock_amt = conn.execute("SELECT stock_amt FROM items WHERE id=?", (item_id,)).fetchone()[0]
    # 전량 출고 시 잔액 전부 대체해 단수차이 미발생
    amt = stock_amt if left == 0 else round(stock_amt * qty / (left + qty))
    conn.execute("UPDATE items SET stock_amt = stock_amt - ? WHERE id=?", (amt, item_id))
    _log(conn, item_id, wh_id, "out", qty, amt, date, ref, ref_id, uid)
    return amt


def valuation(conn, book, date_to):
    return [dict(r) for r in conn.execute(
        """SELECT i.id, i.item_code, i.item_name, i.unit,
                  SUM(CASE WHEN st.trans_type='out' THEN -st.quantity ELSE st.quantity END) AS qty,
                  SUM(CASE WHEN st.trans_type='out' THEN -st.amount ELSE st.amount END) AS amt
           FROM stock_transactions st JOIN items i ON i.id=st.item_id
           WHERE i.company_id=? AND st.trans_date<=?
           GROUP BY i.id HAVING qty<>0 OR amt<>0 ORDER BY i.item_code""",
        (book, date_to),
    ).fetchall()]

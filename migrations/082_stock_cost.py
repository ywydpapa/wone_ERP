# 재고 이동평균 원가. 품목별 재고금액(stock_amt) 보유, 수불 이력에 금액 기록
# 기존 재고는 이력이 없음. 기초(open) 입고로 등록. 단가는 최근 발주 단가, 없으면 0


def up(conn):
    conn.execute("ALTER TABLE items ADD COLUMN stock_amt INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE stock_transactions ADD COLUMN amount INTEGER NOT NULL DEFAULT 0")
    conn.execute("UPDATE accounts SET name='상품매출원가' WHERE code='451' AND name='상품매입'")

    for s in conn.execute(
        """SELECT s.item_id, s.warehouse_id, s.quantity,
                  (SELECT pl.unit_price FROM po_lines pl WHERE pl.item_id=s.item_id ORDER BY pl.id DESC LIMIT 1) AS price
           FROM stock s WHERE s.quantity > 0"""
    ).fetchall():
        amt = round(s[2] * (s[3] or 0))
        conn.execute(
            """INSERT INTO stock_transactions (item_id, warehouse_id, trans_date, trans_type, quantity,
                   ref_type, balance_qty, amount, notes)
               VALUES (?,?,date('now','localtime'),'in',?,'open',?,?,'원가 도입 기초재고')""",
            (s[0], s[1], s[2], s[2], amt),
        )
        conn.execute("UPDATE items SET stock_amt = stock_amt + ? WHERE id=?", (amt, s[0]))

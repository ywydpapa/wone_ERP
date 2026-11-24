def add_po_line(conn, po_id, line_no, item_id, qty, price, amount, acct, dept, proj):
    conn.execute(
        """INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount, account_code, dept, project_code)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (po_id, line_no, item_id, qty, price, amount, acct, dept, proj),
    )

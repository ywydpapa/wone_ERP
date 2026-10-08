# 품목/창고 회사별 분리 (테넌트 격리)

BY_TASK = """SELECT wr.company_id FROM tasks t JOIN work_requests wr ON t.work_request_id = wr.id
             WHERE t.id = ?"""
BY_USER = """SELECT COALESCE((SELECT company_id FROM client_users WHERE user_id = ?),
                      (SELECT company_id FROM employees WHERE user_id = ?))"""


def _rebuild_tables(conn):
    conn.executescript("""
        PRAGMA foreign_keys = OFF;

        CREATE TABLE items_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL DEFAULT 0,
            item_code TEXT NOT NULL,
            item_name TEXT NOT NULL,
            item_type TEXT CHECK(item_type IN ('material','product','semi','consumable')) DEFAULT 'material',
            unit TEXT DEFAULT 'EA',
            unit_price INTEGER DEFAULT 0,
            safety_stock INTEGER DEFAULT 0,
            category TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            created_by INTEGER REFERENCES users(id),
            task_id INTEGER REFERENCES tasks(id),
            UNIQUE(company_id, item_code)
        );
        INSERT INTO items_new (id, company_id, item_code, item_name, item_type, unit, unit_price,
                                safety_stock, category, is_active, created_at, created_by, task_id)
            SELECT id, 0, item_code, item_name, item_type, unit, unit_price,
                   safety_stock, category, is_active, created_at, created_by, task_id FROM items;
        DROP TABLE items;
        ALTER TABLE items_new RENAME TO items;
        CREATE INDEX IF NOT EXISTS idx_items_company ON items(company_id);

        CREATE TABLE warehouses_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL DEFAULT 0,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            location TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_by INTEGER REFERENCES users(id),
            UNIQUE(company_id, code)
        );
        INSERT INTO warehouses_new (id, company_id, code, name, location, is_active, created_by)
            SELECT id, 0, code, name, location, is_active, created_by FROM warehouses;
        DROP TABLE warehouses;
        ALTER TABLE warehouses_new RENAME TO warehouses;
        CREATE INDEX IF NOT EXISTS idx_warehouses_company ON warehouses(company_id);

        PRAGMA foreign_keys = ON;
    """)


def _fallback_company(conn, created_by, task_id):
    cid = None
    if created_by:
        row = conn.execute(BY_USER, (created_by, created_by)).fetchone()
        cid = row[0] if row else None
    if cid is None and task_id:
        row = conn.execute(BY_TASK, (task_id,)).fetchone()
        cid = row[0] if row else None
    return cid if cid is not None else 0


def _item_company_counts(conn, item_id):
    counts = {}

    def add(cid, n):
        if cid is None:
            return
        counts[cid] = counts.get(cid, 0) + n

    for sql in (
        "SELECT po.company_id, COUNT(*) FROM po_lines pl JOIN purchase_orders po ON pl.po_id=po.id WHERE pl.item_id=? GROUP BY po.company_id",
        "SELECT q.company_id, COUNT(*) FROM quote_lines ql JOIN quotations q ON ql.quote_id=q.id WHERE ql.item_id=? GROUP BY q.company_id",
        "SELECT so.company_id, COUNT(*) FROM so_lines sl JOIN sales_orders so ON sl.so_id=so.id WHERE sl.item_id=? GROUP BY so.company_id",
        "SELECT gr.company_id, COUNT(*) FROM gr_lines gl JOIN goods_receipts gr ON gl.gr_id=gr.id WHERE gl.item_id=? GROUP BY gr.company_id",
        "SELECT sh.company_id, COUNT(*) FROM ship_lines shl JOIN shipments sh ON shl.ship_id=sh.id WHERE shl.item_id=? GROUP BY sh.company_id",
        "SELECT pr.company_id, COUNT(*) FROM pr_lines prl JOIN purchase_requisitions pr ON prl.pr_id=pr.id WHERE prl.item_id=? GROUP BY pr.company_id",
        "SELECT bh.company_id, COUNT(*) FROM bom_lines bl JOIN bom_headers bh ON bl.bom_id=bh.id WHERE bl.component_id=? GROUP BY bh.company_id",
    ):
        for row in conn.execute(sql, (item_id,)):
            add(row[0], row[1])

    for row in conn.execute("SELECT company_id, COUNT(*) FROM bom_headers WHERE product_id=? GROUP BY company_id", (item_id,)):
        add(row[0], row[1])
    for row in conn.execute("SELECT company_id, COUNT(*) FROM work_orders WHERE product_id=? GROUP BY company_id", (item_id,)):
        add(row[0], row[1])

    return counts


def _clone_item(conn, item_id, company_id):
    row = conn.execute(
        """SELECT item_code, item_name, item_type, unit, unit_price, safety_stock,
               category, is_active, created_at, created_by, task_id FROM items WHERE id=?""",
        (item_id,),
    ).fetchone()
    existing = conn.execute(
        "SELECT id FROM items WHERE item_code=? AND company_id=?", (row[0], company_id)
    ).fetchone()
    if existing:
        return existing[0]
    cur = conn.execute(
        """INSERT INTO items (company_id, item_code, item_name, item_type, unit, unit_price,
               safety_stock, category, is_active, created_at, created_by, task_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (company_id, *row),
    )
    return cur.lastrowid


def _remap_item_refs(conn, old_id, new_id, cid):
    conn.execute(
        "UPDATE po_lines SET item_id=? WHERE item_id=? AND po_id IN (SELECT id FROM purchase_orders WHERE company_id=?)",
        (new_id, old_id, cid),
    )
    conn.execute(
        "UPDATE quote_lines SET item_id=? WHERE item_id=? AND quote_id IN (SELECT id FROM quotations WHERE company_id=?)",
        (new_id, old_id, cid),
    )
    conn.execute(
        "UPDATE so_lines SET item_id=? WHERE item_id=? AND so_id IN (SELECT id FROM sales_orders WHERE company_id=?)",
        (new_id, old_id, cid),
    )
    conn.execute(
        "UPDATE gr_lines SET item_id=? WHERE item_id=? AND gr_id IN (SELECT id FROM goods_receipts WHERE company_id=?)",
        (new_id, old_id, cid),
    )
    conn.execute(
        "UPDATE ship_lines SET item_id=? WHERE item_id=? AND ship_id IN (SELECT id FROM shipments WHERE company_id=?)",
        (new_id, old_id, cid),
    )
    conn.execute(
        "UPDATE pr_lines SET item_id=? WHERE item_id=? AND pr_id IN (SELECT id FROM purchase_requisitions WHERE company_id=?)",
        (new_id, old_id, cid),
    )
    conn.execute("UPDATE bom_headers SET product_id=? WHERE product_id=? AND company_id=?", (new_id, old_id, cid))
    conn.execute(
        "UPDATE bom_lines SET component_id=? WHERE component_id=? AND bom_id IN (SELECT id FROM bom_headers WHERE company_id=?)",
        (new_id, old_id, cid),
    )
    conn.execute("UPDATE work_orders SET product_id=? WHERE product_id=? AND company_id=?", (new_id, old_id, cid))
    conn.execute(
        """UPDATE stock_transactions SET item_id=? WHERE item_id=? AND (
               (ref_type='gr' AND ref_id IN (SELECT id FROM goods_receipts WHERE company_id=?))
               OR (ref_type='ship' AND ref_id IN (SELECT id FROM shipments WHERE company_id=?))
               OR (ref_type IN ('wo_material','wo_product') AND ref_id IN (SELECT id FROM work_orders WHERE company_id=?)))""",
        (new_id, old_id, cid, cid, cid),
    )


def _backfill_items(conn):
    rows = conn.execute("SELECT id, created_by, task_id FROM items").fetchall()
    for r in rows:
        item_id, created_by, task_id = r[0], r[1], r[2]
        counts = _item_company_counts(conn, item_id)
        if counts:
            winner = max(counts.items(), key=lambda kv: kv[1])[0]
            conn.execute("UPDATE items SET company_id=? WHERE id=?", (winner, item_id))
            for cid in counts:
                if cid == winner:
                    continue
                clone_id = _clone_item(conn, item_id, cid)
                _remap_item_refs(conn, item_id, clone_id, cid)
        else:
            conn.execute("UPDATE items SET company_id=? WHERE id=?", (_fallback_company(conn, created_by, task_id), item_id))


def _wh_company_counts(conn, wh_id):
    counts = {}

    def add(cid, n):
        if cid is None:
            return
        counts[cid] = counts.get(cid, 0) + n

    for row in conn.execute("SELECT company_id, COUNT(*) FROM goods_receipts WHERE warehouse_id=? GROUP BY company_id", (wh_id,)):
        add(row[0], row[1])
    for row in conn.execute("SELECT company_id, COUNT(*) FROM shipments WHERE warehouse_id=? GROUP BY company_id", (wh_id,)):
        add(row[0], row[1])
    for row in conn.execute(
        "SELECT i.company_id, COUNT(*) FROM stock s JOIN items i ON s.item_id=i.id WHERE s.warehouse_id=? GROUP BY i.company_id",
        (wh_id,),
    ):
        add(row[0], row[1])
    for row in conn.execute(
        "SELECT i.company_id, COUNT(*) FROM stock_transactions st JOIN items i ON st.item_id=i.id WHERE st.warehouse_id=? GROUP BY i.company_id",
        (wh_id,),
    ):
        add(row[0], row[1])
    return counts


def _clone_wh(conn, wh_id, company_id):
    row = conn.execute("SELECT code, name, location, is_active, created_by FROM warehouses WHERE id=?", (wh_id,)).fetchone()
    existing = conn.execute("SELECT id FROM warehouses WHERE code=? AND company_id=?", (row[0], company_id)).fetchone()
    if existing:
        return existing[0]
    cur = conn.execute(
        "INSERT INTO warehouses (company_id, code, name, location, is_active, created_by) VALUES (?,?,?,?,?,?)",
        (company_id, *row),
    )
    return cur.lastrowid


def _remap_wh_refs(conn, old_id, new_id, cid):
    conn.execute("UPDATE goods_receipts SET warehouse_id=? WHERE warehouse_id=? AND company_id=?", (new_id, old_id, cid))
    conn.execute("UPDATE shipments SET warehouse_id=? WHERE warehouse_id=? AND company_id=?", (new_id, old_id, cid))

    stock_rows = conn.execute(
        "SELECT s.id, s.item_id, s.quantity FROM stock s JOIN items i ON s.item_id=i.id WHERE s.warehouse_id=? AND i.company_id=?",
        (old_id, cid),
    ).fetchall()
    for sr in stock_rows:
        sid, item_id, qty = sr[0], sr[1], sr[2]
        existing = conn.execute("SELECT id, quantity FROM stock WHERE item_id=? AND warehouse_id=?", (item_id, new_id)).fetchone()
        if existing:
            conn.execute("UPDATE stock SET quantity=quantity+? WHERE id=?", (qty, existing[0]))
            conn.execute("DELETE FROM stock WHERE id=?", (sid,))
        else:
            conn.execute("UPDATE stock SET warehouse_id=? WHERE id=?", (new_id, sid))

    conn.execute(
        "UPDATE stock_transactions SET warehouse_id=? WHERE warehouse_id=? AND item_id IN (SELECT id FROM items WHERE company_id=?)",
        (new_id, old_id, cid),
    )


def _backfill_warehouses(conn):
    rows = conn.execute("SELECT id, created_by FROM warehouses").fetchall()
    for r in rows:
        wh_id, created_by = r[0], r[1]
        counts = _wh_company_counts(conn, wh_id)
        if counts:
            winner = max(counts.items(), key=lambda kv: kv[1])[0]
            conn.execute("UPDATE warehouses SET company_id=? WHERE id=?", (winner, wh_id))
            for cid in counts:
                if cid == winner:
                    continue
                clone_id = _clone_wh(conn, wh_id, cid)
                _remap_wh_refs(conn, wh_id, clone_id, cid)
        else:
            conn.execute("UPDATE warehouses SET company_id=? WHERE id=?", (_fallback_company(conn, created_by, None), wh_id))


def up(conn):
    _rebuild_tables(conn)
    _backfill_items(conn)
    _backfill_warehouses(conn)
    conn.commit()

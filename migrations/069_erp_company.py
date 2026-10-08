TABLES = ("purchase_orders", "quotations", "sales_orders", "goods_receipts",
          "shipments", "bom_headers", "work_orders", "purchase_requisitions")

BY_TASK = """(SELECT wr.company_id FROM tasks t JOIN work_requests wr ON t.work_request_id = wr.id
              WHERE t.id = {t}.task_id)"""
BY_USER = """COALESCE((SELECT company_id FROM client_users WHERE user_id = {t}.created_by),
                      (SELECT company_id FROM employees WHERE user_id = {t}.created_by))"""


def up(conn):
    for t in TABLES:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        if "company_id" not in cols:
            conn.execute(f"ALTER TABLE {t} ADD COLUMN company_id INTEGER")

    for t in ("purchase_orders", "quotations", "sales_orders"):
        conn.execute(f"""UPDATE {t} SET company_id = COALESCE(
            (SELECT company_id FROM partners WHERE id = {t}.partner_id),
            {BY_TASK.format(t=t)}, {BY_USER.format(t=t)}) WHERE company_id IS NULL""")

    conn.execute("""UPDATE goods_receipts SET company_id =
        (SELECT company_id FROM purchase_orders WHERE id = goods_receipts.po_id) WHERE company_id IS NULL""")
    conn.execute("""UPDATE shipments SET company_id =
        (SELECT company_id FROM sales_orders WHERE id = shipments.so_id) WHERE company_id IS NULL""")

    for t in ("bom_headers", "work_orders"):
        conn.execute(f"""UPDATE {t} SET company_id = COALESCE({BY_TASK.format(t=t)}, {BY_USER.format(t=t)})
            WHERE company_id IS NULL""")

    conn.execute("""UPDATE purchase_requisitions SET company_id = COALESCE(
        (SELECT company_id FROM client_users WHERE user_id = purchase_requisitions.requester_id),
        (SELECT company_id FROM employees WHERE user_id = purchase_requisitions.requester_id)) WHERE company_id IS NULL""")

    for t in TABLES:
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_company ON {t}(company_id)")

def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tax_invoices)")}
    if "amend_reason" not in cols:
        conn.execute("ALTER TABLE tax_invoices ADD COLUMN amend_reason INTEGER")

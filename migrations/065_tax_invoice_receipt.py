def up(conn):
    conn.executescript("""
        ALTER TABLE tax_invoices ADD COLUMN receipt_type TEXT DEFAULT '청구';
        ALTER TABLE tax_invoices ADD COLUMN remark TEXT DEFAULT '';
        ALTER TABLE tax_invoice_items ADD COLUMN note TEXT DEFAULT '';
    """)

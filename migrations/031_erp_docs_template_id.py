def up(conn):
    conn.executescript("""
        ALTER TABLE erp_docs ADD COLUMN template_id INTEGER;
    """)

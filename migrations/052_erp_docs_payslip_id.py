import sqlite3

def up(conn):
    try:
        conn.execute("ALTER TABLE erp_docs ADD COLUMN payslip_id INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    conn.commit()

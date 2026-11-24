# 내국신용장 사후개설(lc_no/lc_open_date), 매입세액 불공제 사유 컬럼 추가


def up(conn):
    conn.execute("ALTER TABLE tax_invoices ADD COLUMN lc_no TEXT DEFAULT ''")
    conn.execute("ALTER TABLE tax_invoices ADD COLUMN lc_open_date TEXT")
    conn.execute("ALTER TABLE tax_invoices ADD COLUMN nondeduct_reason INTEGER")
    conn.commit()

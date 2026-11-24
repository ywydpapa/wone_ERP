# 구매 계정 지정. 품목 재고관리 여부/기본 비용계정, PR/PO 라인 계정/부서/프로젝트 승계


def up(conn):
    conn.execute("ALTER TABLE items ADD COLUMN is_stock INTEGER NOT NULL DEFAULT 1")
    conn.execute("ALTER TABLE items ADD COLUMN account_code TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE pr_lines ADD COLUMN account_code TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE pr_lines ADD COLUMN dept TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE pr_lines ADD COLUMN project_code TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE po_lines ADD COLUMN account_code TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE po_lines ADD COLUMN dept TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE po_lines ADD COLUMN project_code TEXT NOT NULL DEFAULT ''")
    conn.commit()

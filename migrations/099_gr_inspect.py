# 입고 검수. 검사대기 입고는 draft로 보관, 재고와 전표는 검사 결과 확정 시 반영


def up(conn):
    conn.execute("ALTER TABLE goods_receipts ADD COLUMN qc_status TEXT NOT NULL DEFAULT ''")

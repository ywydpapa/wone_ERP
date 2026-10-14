# 구매/판매 반품. 입고/출고 문서를 kind로 구분, 원 라인 참조
# status CHECK가 draft/confirmed 뿐이므로 반품 취소는 canceled_at으로 표시


def up(conn):
    for sql in (
        "ALTER TABLE goods_receipts ADD COLUMN kind TEXT NOT NULL DEFAULT '입고'",
        "ALTER TABLE goods_receipts ADD COLUMN canceled_at TEXT",
        "ALTER TABLE shipments ADD COLUMN kind TEXT NOT NULL DEFAULT '출고'",
        "ALTER TABLE shipments ADD COLUMN canceled_at TEXT",
        "ALTER TABLE gr_lines ADD COLUMN orig_line_id INTEGER REFERENCES gr_lines(id)",
        "ALTER TABLE ship_lines ADD COLUMN orig_line_id INTEGER REFERENCES ship_lines(id)",
        "ALTER TABLE po_lines ADD COLUMN returned_qty REAL NOT NULL DEFAULT 0",
        "ALTER TABLE so_lines ADD COLUMN returned_qty REAL NOT NULL DEFAULT 0",
        "CREATE INDEX IF NOT EXISTS idx_gr_lines_orig ON gr_lines(orig_line_id)",
        "CREATE INDEX IF NOT EXISTS idx_ship_lines_orig ON ship_lines(orig_line_id)",
    ):
        conn.execute(sql)

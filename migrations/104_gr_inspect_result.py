# 입고 검사 결과 저장. 검사대기 입고 상세에서 라인별 합격/불량 수량, 메모 입력


def up(conn):
    conn.execute("ALTER TABLE gr_lines ADD COLUMN inspect_pass_qty INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE gr_lines ADD COLUMN inspect_fail_qty INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE goods_receipts ADD COLUMN inspect_memo TEXT NOT NULL DEFAULT ''")

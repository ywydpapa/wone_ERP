# 급여 지급 처리 추가. 확정 시점에는 미지급금(254)만 반영, 실제 지급 시 별도 전표 생성
# 이미 확정된 명세서는 기존 로직대로 보통예금에서 빠졌으므로 지급 완료로 간주


def up(conn):
    conn.execute("ALTER TABLE payslips ADD COLUMN paid_at TEXT")
    conn.execute("ALTER TABLE payslips ADD COLUMN pay_doc_id INTEGER")
    conn.execute("UPDATE payslips SET paid_at=COALESCE(pay_date, created_at) WHERE status='confirmed'")

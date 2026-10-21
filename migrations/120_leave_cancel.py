# 승인 휴가 취소 결재 연결. 취소 사유는 직권 취소와 취소 결재 공통


def up(conn):
    conn.execute("ALTER TABLE leave_requests ADD COLUMN cancel_doc_id INTEGER REFERENCES erp_docs(id)")
    conn.execute("ALTER TABLE leave_requests ADD COLUMN cancel_reason TEXT")
    conn.commit()

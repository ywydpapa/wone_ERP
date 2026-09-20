# review 상태 요청을 submitted로 되돌림 (staff 검토 단계 제거)

def up(conn):
    conn.execute("UPDATE work_requests SET status='submitted' WHERE status='review'")

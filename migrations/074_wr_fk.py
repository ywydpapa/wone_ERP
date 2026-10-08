# 034에서 work_requests RENAME 때 자식 테이블 FK가 "_wr_old"로 바뀐 채 남음.
# foreign_keys=ON 상태. 해당 컬럼 INSERT가 전부 no such table 로 실패. FK 대상만 수정
def up(conn):
    conn.commit()
    ver = conn.execute("PRAGMA schema_version").fetchone()[0]
    conn.execute("PRAGMA writable_schema = ON")
    conn.execute("""UPDATE sqlite_master SET sql = replace(sql, 'REFERENCES "_wr_old"(id)', 'REFERENCES work_requests(id)')
                    WHERE type = 'table' AND sql LIKE '%REFERENCES "_wr_old"(id)%'""")
    conn.execute(f"PRAGMA schema_version = {ver + 1}")
    conn.execute("PRAGMA writable_schema = OFF")
    conn.commit()

# 그룹웨어 문서는 생성 시 장부를 기록하지 않았음. 작성자 소속으로 백필


def up(conn):
    conn.execute("""
        UPDATE erp_docs SET company_id = COALESCE(
            (SELECT company_id FROM client_users WHERE user_id = erp_docs.user_id),
            (SELECT company_id FROM employees WHERE user_id = erp_docs.user_id), 0)
        WHERE doc_type NOT IN ('expense', 'slip') AND company_id = 0
    """)

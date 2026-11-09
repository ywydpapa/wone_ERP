# 병가 증빙 필수 기준 일수. 회사 취업규칙별 상이, 0이면 미요구


def up(conn):
    conn.execute("ALTER TABLE client_companies ADD COLUMN sick_doc_days INTEGER NOT NULL DEFAULT 3")
    conn.commit()

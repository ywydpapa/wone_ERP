# 고객사가 고른 반출 양식. 반출 화면 기본 선택값, 빈 값이면 표준 양식


def up(conn):
    conn.execute("ALTER TABLE client_companies ADD COLUMN export_set TEXT NOT NULL DEFAULT ''")
    conn.commit()

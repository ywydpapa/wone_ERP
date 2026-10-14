# 급여 이체 파일 생성 이력, 장애인 의무고용률 산정용 공공/민간 구분


def up(conn):
    conn.execute("ALTER TABLE payslips ADD COLUMN transfer_file_at TEXT")
    conn.execute("ALTER TABLE client_companies ADD COLUMN sector TEXT NOT NULL DEFAULT '민간'")

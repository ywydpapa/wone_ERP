# 별지 제15호서식 첨부 장애인 근로자 명부. 근무직무는 한국표준직업분류 코드(1~9)


def up(conn):
    conn.execute("ALTER TABLE employees ADD COLUMN job_code TEXT")
    conn.commit()

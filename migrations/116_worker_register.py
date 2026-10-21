# 근로기준법 시행규칙 별지 제16호서식 근로자명부 + 장애인정 정보
NEW_COLS = [
    ("renew_date", "TEXT"),
    ("contract_end", "TEXT"),
    ("career", "TEXT"),
    ("education", "TEXT"),
    ("military", "TEXT"),
    ("license", "TEXT"),
    ("training", "TEXT"),
    ("disability_class", "TEXT"),
    ("veteran_grade", "TEXT"),
    ("disability_date", "TEXT"),
]


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(employees)")}
    for name, coltype in NEW_COLS:
        if name not in cols:
            conn.execute(f"ALTER TABLE employees ADD COLUMN {name} {coltype}")
    conn.commit()

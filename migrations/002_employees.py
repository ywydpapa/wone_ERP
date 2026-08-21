
CREATE_EMPLOYEES = """
CREATE TABLE IF NOT EXISTS employees (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER,
    name               TEXT NOT NULL,
    employee_no        TEXT UNIQUE,
    dept               TEXT NOT NULL DEFAULT '경영지원팀',
    position           TEXT NOT NULL DEFAULT '사원',
    hire_date          TEXT,
    status             TEXT NOT NULL DEFAULT 'active'
                           CHECK(status IN ('active','on_leave','retired')),
    disability_type    TEXT DEFAULT '',
    disability_grade   TEXT DEFAULT '',
    emergency_contact  TEXT DEFAULT '',
    emergency_phone    TEXT DEFAULT '',
    notes              TEXT DEFAULT '',
    created_at         TEXT DEFAULT (datetime('now','localtime')),
    updated_at         TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id)
)
"""

SEED_EMPLOYEES = [
    # (user_id, name, employee_no, dept, position, hire_date, status, disability_type, disability_grade)
    (1, "관리자",  "EMP-001", "경영지원팀", "팀장",  "2020-01-02", "active",   "",       ""),
    (2, "홍길동",  "EMP-002", "개발팀",     "대리",  "2021-03-15", "active",   "지체장애", "3급"),
    (3, "김영희",  "EMP-003", "영업팀",     "사원",  "2022-07-01", "on_leave", "시각장애", "4급"),
]


def up(conn):
    conn.execute(CREATE_EMPLOYEES)
    conn.commit()

    for user_id, name, employee_no, dept, position, hire_date, status, dtype, dgrade in SEED_EMPLOYEES:
        try:
            conn.execute(
                """INSERT INTO employees
                   (user_id, name, employee_no, dept, position, hire_date, status,
                    disability_type, disability_grade)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (user_id, name, employee_no, dept, position, hire_date, status, dtype, dgrade),
            )
        except Exception:
            pass
    conn.commit()

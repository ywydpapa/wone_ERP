# 근로계약서 작성/전자서명/교부. 근로기준법 제17조, 기간제법 제17조 명시사항 기준


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS labor_contracts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id          INTEGER REFERENCES client_companies(id),
            employee_id         INTEGER NOT NULL REFERENCES employees(id),
            version             INTEGER NOT NULL DEFAULT 1,
            prev_id             INTEGER REFERENCES labor_contracts(id),
            kind                TEXT NOT NULL DEFAULT '일반' CHECK(kind IN ('일반','단시간')),
            has_term            INTEGER NOT NULL DEFAULT 1,
            start_date          TEXT NOT NULL,
            end_date            TEXT DEFAULT '',
            place               TEXT NOT NULL DEFAULT '',
            duty                TEXT NOT NULL DEFAULT '',
            work_days           TEXT DEFAULT '',
            work_start          TEXT DEFAULT '',
            work_end            TEXT DEFAULT '',
            break_min           INTEGER DEFAULT 60,
            weekly_hours        REAL DEFAULT 0,
            daily_hours_json    TEXT DEFAULT '',
            holidays            TEXT DEFAULT '매주 일요일(주휴일)',
            wage_type           TEXT NOT NULL DEFAULT '월급' CHECK(wage_type IN ('월급','시급','일급')),
            base_pay            INTEGER NOT NULL DEFAULT 0,
            allowances_json     TEXT DEFAULT '[]',
            pay_day             TEXT DEFAULT '매월 25일',
            pay_method          TEXT DEFAULT '근로자 명의 계좌로 지급',
            annual_leave        TEXT DEFAULT '근로기준법 제60조에 따라 부여',
            insurance           TEXT DEFAULT '고용보험,산재보험,국민연금,건강보험',
            etc_terms           TEXT DEFAULT '',
            status              TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','sent','signed')),
            body_html           TEXT,
            body_hash           TEXT,
            employer_signed_by  INTEGER REFERENCES users(id),
            employer_signed_at  TEXT,
            employer_sign_ip    TEXT,
            worker_signed_at    TEXT,
            worker_sign_ip      TEXT,
            worker_sign_name    TEXT,
            delivered_at        TEXT,
            created_by          INTEGER REFERENCES users(id),
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            updated_at          TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_labor_contracts_employee ON labor_contracts(employee_id, id);
        CREATE INDEX IF NOT EXISTS idx_labor_contracts_company ON labor_contracts(company_id);
    """)

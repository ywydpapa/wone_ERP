def up(conn):
    stmts = [
        # employees 누락 필드
        "ALTER TABLE employees ADD COLUMN resident_no TEXT DEFAULT ''",
        "ALTER TABLE employees ADD COLUMN job_title TEXT DEFAULT ''",
        "ALTER TABLE employees ADD COLUMN monthly_work_hours INTEGER DEFAULT 0",
        "ALTER TABLE employees ADD COLUMN employment_insurance INTEGER DEFAULT 1",
        "ALTER TABLE employees ADD COLUMN disability_cert_file TEXT DEFAULT ''",

        # client_companies 누락 필드
        "ALTER TABLE client_companies ADD COLUMN representative TEXT DEFAULT ''",
        "ALTER TABLE client_companies ADD COLUMN address TEXT DEFAULT ''",
        "ALTER TABLE client_companies ADD COLUMN employee_count INTEGER DEFAULT 0",
        "ALTER TABLE client_companies ADD COLUMN contract_amount INTEGER DEFAULT 0",
        "ALTER TABLE client_companies ADD COLUMN contract_content TEXT DEFAULT ''",
        "ALTER TABLE client_companies ADD COLUMN logo_file TEXT DEFAULT ''",

        # attendance 누락 필드
        "ALTER TABLE attendance ADD COLUMN overtime_minutes INTEGER DEFAULT 0",
        "ALTER TABLE attendance ADD COLUMN break_minutes INTEGER DEFAULT 0",

        # 성능 인덱스
        "CREATE INDEX IF NOT EXISTS idx_employees_company ON employees(company_id)",
        "CREATE INDEX IF NOT EXISTS idx_payslips_period ON payslips(pay_year, pay_month)",
        "CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(work_date)",
        "CREATE INDEX IF NOT EXISTS idx_leave_requests_employee ON leave_requests(employee_id)",
    ]
    for s in stmts:
        try:
            conn.execute(s)
        except Exception:
            pass
    conn.commit()

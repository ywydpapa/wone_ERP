
def up(conn):
    try:
        conn.execute("ALTER TABLE client_users ADD COLUMN client_role TEXT DEFAULT 'all'")
    except Exception:
        pass

    try:
        conn.execute("ALTER TABLE employees ADD COLUMN birth_date TEXT")
    except Exception:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS payslips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            pay_year INTEGER NOT NULL,
            pay_month INTEGER NOT NULL,
            base_salary INTEGER NOT NULL,
            overtime_pay INTEGER DEFAULT 0,
            disability_allowance INTEGER DEFAULT 0,
            meal_allowance INTEGER DEFAULT 0,
            gross_pay INTEGER NOT NULL,
            income_tax INTEGER DEFAULT 0,
            resident_tax INTEGER DEFAULT 0,
            national_pension INTEGER DEFAULT 0,
            health_insurance INTEGER DEFAULT 0,
            employment_insurance INTEGER DEFAULT 0,
            total_deduction INTEGER NOT NULL,
            net_pay INTEGER NOT NULL,
            pay_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(employee_id, pay_year, pay_month)
        )
    """)

    try:
        conn.execute("ALTER TABLE payslips ADD COLUMN status TEXT DEFAULT 'confirmed'")
    except Exception:
        pass

    conn.execute("UPDATE payslips SET status='confirmed' WHERE status IS NULL")

    conn.commit()

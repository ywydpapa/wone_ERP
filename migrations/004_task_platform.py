def up(conn):
    c = conn.cursor()

    # 역할명 변경
    c.execute("UPDATE users SET role='platform_staff' WHERE role='admin'")
    c.execute("UPDATE users SET role='worker' WHERE role='employee'")

    c.execute("""
        CREATE TABLE IF NOT EXISTS client_companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            business_no TEXT UNIQUE,
            contact_name TEXT DEFAULT '',
            contact_phone TEXT DEFAULT '',
            contact_email TEXT DEFAULT '',
            contract_start TEXT,
            contract_end TEXT,
            status TEXT DEFAULT 'active' CHECK(status IN ('active','inactive')),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS client_users (
            user_id INTEGER NOT NULL REFERENCES users(id),
            company_id INTEGER NOT NULL REFERENCES client_companies(id),
            PRIMARY KEY (user_id, company_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS work_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES client_companies(id),
            requested_by INTEGER REFERENCES users(id),
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            task_type TEXT NOT NULL,
            volume INTEGER DEFAULT 1,
            priority TEXT DEFAULT 'normal' CHECK(priority IN ('low','normal','high','urgent')),
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','accepted','in_progress','completed','cancelled')),
            due_date TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_request_id INTEGER REFERENCES work_requests(id),
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            task_type TEXT NOT NULL,
            assigned_to INTEGER REFERENCES employees(id),
            assigned_by INTEGER REFERENCES users(id),
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','assigned','in_progress','review','completed','returned','cancelled')),
            priority TEXT DEFAULT 'normal' CHECK(priority IN ('low','normal','high','urgent')),
            due_date TEXT,
            started_at TEXT,
            completed_at TEXT,
            review_notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL REFERENCES employees(id),
            work_date TEXT NOT NULL,
            clock_in TEXT,
            clock_out TEXT,
            work_minutes INTEGER DEFAULT 0,
            status TEXT DEFAULT 'normal' CHECK(status IN ('normal','late','early_leave','absent','holiday')),
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_emp_date ON attendance(employee_id, work_date)")

    # 샘플 거래처
    c.execute("""
        INSERT INTO client_companies (name, business_no, contact_name, contact_phone)
        VALUES ('한빛전자', '123-45-67890', '이수진', '02-1234-5678')
    """)
    company_id = c.lastrowid

    # 거래처 담당자 계정
    import hashlib
    pw = hashlib.sha256('1234'.encode()).hexdigest()
    c.execute("""
        INSERT INTO users (username, password, name, dept, role)
        VALUES ('client1', ?, '이수진', '한빛전자', 'client')
    """, (pw,))
    client_user_id = c.lastrowid
    c.execute("INSERT INTO client_users (user_id, company_id) VALUES (?, ?)",
              (client_user_id, company_id))

    # 샘플 업무 요청
    c.execute("""
        INSERT INTO work_requests (company_id, requested_by, title, description, task_type, volume, priority, status)
        VALUES (?, ?, '8월 전표 입력', '8월분 매입매출 전표 200건 입력', 'data_entry', 200, 'normal', 'accepted')
    """, (company_id, client_user_id))

    conn.commit()

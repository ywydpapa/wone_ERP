import hashlib
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "erp.db")


def pw(plain):
    return hashlib.sha256(plain.encode()).hexdigest()


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 거래처
    companies = [
        ("한양정밀",       "211-81-00001", "김대표", "031-999-1111", "", "2026-01-01", None, "active"),
        ("그린테크솔루션", "214-87-00002", "박대표", "02-555-2222",  "", "2026-02-01", None, "active"),
        ("대한물류",       "130-86-00003", "최대표", "032-777-3333", "", "2026-03-01", None, "active"),
    ]

    company_ids = {}
    # 기존 migration에서 만든 회사도 포함
    for row in c.execute("SELECT id, name FROM client_companies").fetchall():
        company_ids[row["name"]] = row["id"]
    for name, biz_no, contact, phone, email, cstart, cend, status in companies:
        row = c.execute("SELECT id FROM client_companies WHERE name=?", (name,)).fetchone()
        if row:
            company_ids[name] = row["id"]
            print(f"  거래처 이미 있음 (skip): {name}")
        else:
            c.execute(
                """INSERT INTO client_companies
                   (name, business_no, contact_name, contact_phone, contact_email,
                    contract_start, contract_end, status)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (name, biz_no, contact, phone, email, cstart, cend, status),
            )
            company_ids[name] = c.lastrowid
            print(f"  거래처 추가: {name} (id={company_ids[name]})")

    conn.commit()

    # 근로자
    workers = [
        ("na_hyunwoo",  "나현우", "경리팀",       "한빛전자",       "EMP-110", "사원", "2025-02-10", "지체장애",   "5급"),
        ("baek_soyeon", "백소연", "총무팀",       "한빛전자",       "EMP-111", "사원", "2025-05-20", "시각장애",   "3급"),
        ("kim_sujin",   "김수진", "데이터처리팀", "한양정밀",       "EMP-101", "사원", "2024-03-02", "지체장애",   "4급"),
        ("park_minho",  "박민호", "데이터처리팀", "한양정밀",       "EMP-102", "사원", "2024-05-13", "뇌병변장애", "3급"),
        ("yoon_sera",   "윤세라", "고객지원팀",   "한양정밀",       "EMP-107", "사원", "2025-04-01", "시각장애",   "4급"),
        ("song_jihoon", "송지훈", "기획팀",       "한양정밀",       "EMP-108", "대리", "2024-11-15", "지체장애",   "5급"),
        ("oh_eunji",    "오은지", "데이터처리팀", "한양정밀",       "EMP-109", "사원", "2025-07-01", "청각장애",   "4급"),
        ("lee_jiyoung", "이지영", "고객지원팀",   "그린테크솔루션", "EMP-103", "사원", "2025-01-06", "청각장애",   "3급"),
        ("jung_wusung", "정우성", "기획팀",       "그린테크솔루션", "EMP-104", "대리", "2024-09-01", "지체장애",   "5급"),
        ("choi_yerin",  "최예린", "데이터처리팀", "대한물류",       "EMP-105", "사원", "2025-03-17", "지체장애",   "4급"),
        ("han_dongwoo", "한동우", "고객지원팀",   "대한물류",       "EMP-106", "사원", "2025-06-02", "언어장애",   "3급"),
    ]

    worker_ids = {}
    user_ids   = {}

    for username, name, dept, company_name, emp_no, position, hire_date, dtype, dgrade in workers:
        user_row = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if user_row:
            uid = user_row["id"]
            print(f"  유저 이미 있음 (skip): {username}")
        else:
            c.execute(
                "INSERT INTO users (username, password, name, dept, role) VALUES (?,?,?,?,?)",
                (username, pw("1234"), name, dept, "worker"),
            )
            uid = c.lastrowid
            print(f"  유저 추가: {username} (id={uid})")
        user_ids[username] = uid

        emp_row = c.execute("SELECT id FROM employees WHERE employee_no=?", (emp_no,)).fetchone()
        if emp_row:
            eid = emp_row["id"]
            c.execute("UPDATE employees SET company_id=? WHERE id=?", (company_ids[company_name], eid))
            print(f"  직원 이미 있음, company_id 갱신: {name}")
        else:
            c.execute(
                """INSERT INTO employees
                   (user_id, name, employee_no, dept, position, hire_date, status,
                    disability_type, disability_grade, company_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (uid, name, emp_no, dept, position, hire_date, "active",
                 dtype, dgrade, company_ids[company_name]),
            )
            eid = c.lastrowid
            print(f"  직원 추가: {name} (id={eid})")
        worker_ids[username] = eid

    conn.commit()

    # 거래처 유저
    client_contacts = [
        ("hanyang_mgr",    "김담당", "한양정밀",       "한양정밀"),
        ("greentech_mgr",  "이담당", "그린테크솔루션", "그린테크솔루션"),
        ("daehan_mgr",     "최담당", "대한물류",       "대한물류"),
    ]

    for username, name, dept, company_name in client_contacts:
        user_row = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if user_row:
            uid = user_row["id"]
            print(f"  클라이언트 유저 이미 있음 (skip): {username}")
        else:
            c.execute(
                "INSERT INTO users (username, password, name, dept, role) VALUES (?,?,?,?,?)",
                (username, pw("1234"), name, dept, "client"),
            )
            uid = c.lastrowid
            print(f"  클라이언트 유저 추가: {username} (id={uid})")

        cid = company_ids[company_name]
        exists = c.execute(
            "SELECT 1 FROM client_users WHERE user_id=? AND company_id=?", (uid, cid)
        ).fetchone()
        if not exists:
            c.execute("INSERT INTO client_users (user_id, company_id) VALUES (?,?)", (uid, cid))
            print(f"  client_users 연결: user_id={uid} -> company_id={cid}")

    conn.commit()

    # 역량 프로필
    cap_profiles = [
        # 김수진: 키보드+마우스 가능, 경도 지체장애
        ("kim_sujin", {
            "hand_left": "precise", "hand_right": "precise",
            "arm_left": "full",     "arm_right": "full",
            "neck": "full",
            "foot_left": "full",    "foot_right": "full",
            "posture_maintenance": 1,
            "vision": "corrected",  "hearing": "normal",
            "eye_movement": 1,      "eyelid_control": 1,
            "speech": "capable",    "breath_control": 1,
            "reading_level": "advanced",
            "sustained_focus": 1,   "memory_aid_needed": 0,
            "continuous_work_minutes": 120,
            "fatigue_pattern": "오후 집중력 저하",
            "posture_change_interval": 60,
            "notes": "경도 지체장애, 양손 사용 가능",
        }),
        # 박민호: 한 손 타이핑, 뇌병변장애
        ("park_minho", {
            "hand_left": "unable",  "hand_right": "precise",
            "arm_left": "unable",   "arm_right": "limited",
            "neck": "full",
            "foot_left": "limited", "foot_right": "full",
            "posture_maintenance": 1,
            "vision": "normal",     "hearing": "normal",
            "eye_movement": 1,      "eyelid_control": 1,
            "speech": "capable",    "breath_control": 1,
            "reading_level": "advanced",
            "sustained_focus": 1,   "memory_aid_needed": 0,
            "continuous_work_minutes": 90,
            "fatigue_pattern": "한 손 타이핑 장시간 시 피로 누적",
            "posture_change_interval": 45,
            "notes": "왼손 사용 불가, 오른손 정밀 동작 가능",
        }),
        # 이지영: 음성+시선 입력, 중증 운동 장애
        ("lee_jiyoung", {
            "hand_left": "unable",  "hand_right": "unable",
            "arm_left": "unable",   "arm_right": "unable",
            "neck": "limited",
            "foot_left": "unable",  "foot_right": "unable",
            "posture_maintenance": 0,
            "vision": "normal",     "hearing": "aided",
            "eye_movement": 1,      "eyelid_control": 1,
            "speech": "capable",    "breath_control": 1,
            "reading_level": "intermediate",
            "sustained_focus": 1,   "memory_aid_needed": 1,
            "continuous_work_minutes": 45,
            "fatigue_pattern": "30~45분 후 체력 저하",
            "posture_change_interval": 30,
            "notes": "양손 사용 불가, 음성 입력 + 시선 포인터 활용",
        }),
        # 한동우: 음성 입력 전용, 상지 장애
        ("han_dongwoo", {
            "hand_left": "gross_only", "hand_right": "unable",
            "arm_left": "limited",     "arm_right": "unable",
            "neck": "full",
            "foot_left": "limited",    "foot_right": "limited",
            "posture_maintenance": 1,
            "vision": "normal",        "hearing": "normal",
            "eye_movement": 1,         "eyelid_control": 1,
            "speech": "capable",       "breath_control": 1,
            "reading_level": "intermediate",
            "sustained_focus": 1,      "memory_aid_needed": 0,
            "continuous_work_minutes": 60,
            "fatigue_pattern": "상지 과부하 주의",
            "posture_change_interval": 40,
            "notes": "오른손 사용 불가, 음성 입력 주력",
        }),
    ]

    for username, fields in cap_profiles:
        eid = worker_ids.get(username)
        if eid is None:
            print(f"  역량 프로필 skip (직원 없음): {username}")
            continue
        exists = c.execute(
            "SELECT id FROM capability_profiles WHERE employee_id=?", (eid,)
        ).fetchone()
        if exists:
            print(f"  역량 프로필 이미 있음 (skip): {username}")
            continue
        c.execute(
            """INSERT INTO capability_profiles
               (employee_id, effective_date,
                hand_left, hand_right, arm_left, arm_right, neck,
                foot_left, foot_right, posture_maintenance,
                vision, hearing, eye_movement, eyelid_control,
                speech, breath_control,
                reading_level, sustained_focus, memory_aid_needed,
                continuous_work_minutes, fatigue_pattern, posture_change_interval,
                notes)
               VALUES
               (?,date('now','localtime'),
                ?,?,?,?,?,
                ?,?,?,
                ?,?,?,?,
                ?,?,
                ?,?,?,
                ?,?,?,
                ?)""",
            (
                eid,
                fields["hand_left"],      fields["hand_right"],
                fields["arm_left"],       fields["arm_right"],
                fields["neck"],
                fields["foot_left"],      fields["foot_right"],
                fields["posture_maintenance"],
                fields["vision"],         fields["hearing"],
                fields["eye_movement"],   fields["eyelid_control"],
                fields["speech"],         fields["breath_control"],
                fields["reading_level"],
                fields["sustained_focus"], fields["memory_aid_needed"],
                fields["continuous_work_minutes"],
                fields["fatigue_pattern"],
                fields["posture_change_interval"],
                fields["notes"],
            ),
        )
        print(f"  역량 프로필 추가: {username} (employee_id={eid})")

    conn.commit()

    # 업무 요청
    requests_data = [
        ("한양정밀",       1, "3월 매입전표 입력",       "3월 매입전표 200건 입력 처리",           "data_entry",      200, "in_progress", "2026-09-15", "kim_sujin",  "excel"),
        ("한양정밀",       1, "거래처 계약서 검토",       "거래처별 계약서 50건 내용 검토 및 정리",  "document_review",  50, "pending",     "2026-09-30", None,         "pdf"),
        ("그린테크솔루션", 1, "고객 문의 채팅 응대",     "9월 고객 채팅 문의 500건 응대",           "chat_support",    500, "accepted",    "2026-09-10", "lee_jiyoung","excel"),
        ("대한물류",       1, "입출고 데이터 정리",       "9~10월 입출고 내역 300건 데이터 정리",    "data_entry",      300, "pending",     "2026-10-01", None,         "erp"),
    ]

    request_ids = {}
    for company_name, req_by, title, desc, ttype, vol, status, due, assigned_username, out_fmt in requests_data:
        exists = c.execute(
            "SELECT id FROM work_requests WHERE title=? AND company_id=?",
            (title, company_ids[company_name]),
        ).fetchone()
        if exists:
            request_ids[title] = exists["id"]
            print(f"  업무 요청 이미 있음 (skip): {title}")
            continue
        assigned_emp = None
        if assigned_username:
            emp_row = c.execute(
                "SELECT e.id FROM employees e JOIN users u ON e.user_id=u.id WHERE u.username=?",
                (assigned_username,),
            ).fetchone()
            if emp_row:
                assigned_emp = emp_row["id"]
        c.execute(
            """INSERT INTO work_requests
               (company_id, requested_by, title, description, task_type, volume, status, due_date,
                assigned_to, assigned_by, output_format)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (company_ids[company_name], req_by, title, desc, ttype, vol, status, due,
             assigned_emp, req_by if assigned_emp else None, out_fmt),
        )
        rid = c.lastrowid
        request_ids[title] = rid
        print(f"  업무 요청 추가: {title} (id={rid})")

    conn.commit()

    # 태스크
    매입전표_rid = request_ids.get("3월 매입전표 입력")
    채팅_rid     = request_ids.get("고객 문의 채팅 응대")

    sujin_id  = worker_ids.get("kim_sujin")
    yerin_id  = worker_ids.get("choi_yerin")
    jiyoung_id = worker_ids.get("lee_jiyoung")

    tasks_data = []

    if 매입전표_rid:
        tasks_data += [
            (매입전표_rid, "매입전표 입력 (1/4)", "data_entry", sujin_id,  "in_progress"),
            (매입전표_rid, "매입전표 입력 (2/4)", "data_entry", sujin_id,  "assigned"),
            (매입전표_rid, "매입전표 입력 (3/4)", "data_entry", yerin_id,  "assigned"),
            (매입전표_rid, "매입전표 입력 (4/4)", "data_entry", None,      "pending"),
        ]

    if 채팅_rid:
        tasks_data += [
            (채팅_rid, "채팅 상담 오전조", "chat_support", jiyoung_id, "in_progress"),
            (채팅_rid, "채팅 상담 오후조", "chat_support", None,       "pending"),
        ]

    for work_request_id, title, ttype, assigned_to, status in tasks_data:
        exists = c.execute(
            "SELECT id FROM tasks WHERE title=? AND work_request_id=?",
            (title, work_request_id),
        ).fetchone()
        if exists:
            print(f"  태스크 이미 있음 (skip): {title}")
            continue
        c.execute(
            """INSERT INTO tasks
               (work_request_id, title, task_type, assigned_to, assigned_by, status)
               VALUES (?,?,?,?,?,?)""",
            (work_request_id, title, ttype, assigned_to, 1, status),
        )
        print(f"  태스크 추가: {title} (request_id={work_request_id}, assigned={assigned_to})")

    conn.commit()

    # 출근 기록
    attendance_data = [
        ("na_hyunwoo",  "2026-08-04", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-05", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-06", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-07", "09:12", "18:00", 468, "late"),
        ("na_hyunwoo",  "2026-08-08", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-11", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-12", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-13", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-14", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-15", None,    None,    0,   "holiday"),
        ("na_hyunwoo",  "2026-08-18", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-19", None,    None,    0,   "absent"),
        ("na_hyunwoo",  "2026-08-20", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-21", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-22", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-25", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-26", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-27", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-28", "09:00", "18:00", 480, "normal"),
        ("na_hyunwoo",  "2026-08-29", "09:00", "18:00", 480, "normal"),

        ("baek_soyeon", "2026-08-04", "08:45", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-05", "08:50", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-06", "08:48", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-07", "08:50", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-08", "08:55", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-11", "08:50", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-12", "08:48", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-13", "08:50", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-14", "08:45", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-15", None,    None,    0,   "holiday"),
        ("baek_soyeon", "2026-08-18", "08:50", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-19", "08:48", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-20", "08:50", "14:00", 270, "early_leave"),
        ("baek_soyeon", "2026-08-21", "08:50", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-22", "08:48", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-25", "08:50", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-26", "08:55", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-27", "08:50", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-28", "08:48", "17:30", 450, "normal"),
        ("baek_soyeon", "2026-08-29", "08:50", "17:30", 450, "normal"),

        ("kim_sujin",   "2026-08-04", "08:55", "18:05", 480, "normal"),
        ("kim_sujin",   "2026-08-05", "09:02", "18:10", 480, "normal"),
        ("kim_sujin",   "2026-08-06", "09:20", "18:00", 450, "late"),
        ("kim_sujin",   "2026-08-07", "08:58", "18:00", 480, "normal"),
        ("kim_sujin",   "2026-08-08", "09:00", "18:00", 480, "normal"),
        ("kim_sujin",   "2026-08-11", "08:50", "18:00", 480, "normal"),
        ("kim_sujin",   "2026-08-12", "09:00", "18:05", 480, "normal"),
        ("kim_sujin",   "2026-08-13", "09:01", "18:00", 480, "normal"),
        ("kim_sujin",   "2026-08-14", "08:57", "18:00", 480, "normal"),
        ("kim_sujin",   "2026-08-15", None,    None,    0,   "holiday"),
        ("kim_sujin",   "2026-08-18", "08:55", "18:00", 480, "normal"),
        ("kim_sujin",   "2026-08-19", "09:00", "18:00", 480, "normal"),
        ("kim_sujin",   "2026-08-20", "09:00", "15:00", 300, "early_leave"),
        ("kim_sujin",   "2026-08-21", "08:58", "18:00", 480, "normal"),
        ("kim_sujin",   "2026-08-22", "09:00", "18:00", 480, "normal"),
        ("kim_sujin",   "2026-08-25", "08:55", "18:00", 480, "normal"),
        ("kim_sujin",   "2026-08-26", "09:00", "18:05", 480, "normal"),
        ("kim_sujin",   "2026-08-27", "09:00", "18:00", 480, "normal"),
        ("kim_sujin",   "2026-08-28", "08:50", "18:00", 480, "normal"),
        ("kim_sujin",   "2026-08-29", "09:00", "18:00", 480, "normal"),

        ("park_minho",  "2026-08-04", "09:10", "18:00", 470, "late"),
        ("park_minho",  "2026-08-05", "08:55", "18:00", 480, "normal"),
        ("park_minho",  "2026-08-06", "09:00", "18:00", 480, "normal"),
        ("park_minho",  "2026-08-07", "09:05", "18:00", 475, "normal"),
        ("park_minho",  "2026-08-08", "09:15", "18:00", 465, "late"),
        ("park_minho",  "2026-08-11", "08:50", "18:00", 480, "normal"),
        ("park_minho",  "2026-08-12", "09:00", "18:00", 480, "normal"),
        ("park_minho",  "2026-08-13", None,    None,    0,   "absent"),
        ("park_minho",  "2026-08-14", "09:00", "18:00", 480, "normal"),
        ("park_minho",  "2026-08-15", None,    None,    0,   "holiday"),
        ("park_minho",  "2026-08-18", "08:58", "18:00", 480, "normal"),
        ("park_minho",  "2026-08-19", "09:00", "18:05", 480, "normal"),
        ("park_minho",  "2026-08-20", "09:00", "18:00", 480, "normal"),
        ("park_minho",  "2026-08-21", "09:02", "18:00", 478, "normal"),
        ("park_minho",  "2026-08-22", "09:00", "18:00", 480, "normal"),
        ("park_minho",  "2026-08-25", "09:00", "18:00", 480, "normal"),
        ("park_minho",  "2026-08-26", "09:00", "18:00", 480, "normal"),
        ("park_minho",  "2026-08-27", "09:15", "18:00", 465, "late"),
        ("park_minho",  "2026-08-28", "08:55", "18:00", 480, "normal"),
        ("park_minho",  "2026-08-29", "09:00", "18:00", 480, "normal"),

        ("lee_jiyoung", "2026-08-04", "08:50", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-05", "08:45", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-06", "08:55", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-07", "08:50", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-08", "08:48", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-11", "08:50", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-12", "08:55", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-13", "08:50", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-14", "09:00", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-15", None,    None,    0,   "holiday"),
        ("lee_jiyoung", "2026-08-18", "08:50", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-19", "08:55", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-20", "08:50", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-21", "08:48", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-22", "08:50", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-25", "08:55", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-26", "08:50", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-27", "08:50", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-28", "08:50", "17:00", 420, "normal"),
        ("lee_jiyoung", "2026-08-29", "08:55", "17:00", 420, "normal"),

        ("jung_wusung", "2026-08-04", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-05", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-06", "09:30", "18:00", 450, "late"),
        ("jung_wusung", "2026-08-07", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-08", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-11", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-12", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-13", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-14", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-15", None,    None,    0,   "holiday"),
        ("jung_wusung", "2026-08-18", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-19", None,    None,    0,   "absent"),
        ("jung_wusung", "2026-08-20", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-21", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-22", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-25", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-26", "09:05", "18:00", 475, "normal"),
        ("jung_wusung", "2026-08-27", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-28", "09:00", "18:00", 480, "normal"),
        ("jung_wusung", "2026-08-29", "09:00", "18:00", 480, "normal"),

        ("choi_yerin",  "2026-08-04", "08:58", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-05", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-06", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-07", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-08", "09:25", "18:00", 455, "late"),
        ("choi_yerin",  "2026-08-11", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-12", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-13", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-14", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-15", None,    None,    0,   "holiday"),
        ("choi_yerin",  "2026-08-18", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-19", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-20", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-21", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-22", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-25", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-26", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-27", "09:00", "18:00", 480, "normal"),
        ("choi_yerin",  "2026-08-28", "09:00", "14:30", 270, "early_leave"),
        ("choi_yerin",  "2026-08-29", "09:00", "18:00", 480, "normal"),

        ("yoon_sera",   "2026-08-04", "08:50", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-05", "08:55", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-06", "09:00", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-07", "09:20", "17:30", 430, "late"),
        ("yoon_sera",   "2026-08-08", "08:50", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-11", "08:55", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-12", "08:50", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-13", "08:48", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-14", "08:55", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-15", None,    None,    0,   "holiday"),
        ("yoon_sera",   "2026-08-18", "08:50", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-19", "08:55", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-20", None,    None,    0,   "absent"),
        ("yoon_sera",   "2026-08-21", "08:50", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-22", "08:55", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-25", "08:50", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-26", "08:48", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-27", "08:55", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-28", "08:50", "17:30", 450, "normal"),
        ("yoon_sera",   "2026-08-29", "08:55", "17:30", 450, "normal"),

        ("song_jihoon", "2026-08-04", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-05", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-06", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-07", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-08", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-11", "09:15", "18:00", 465, "late"),
        ("song_jihoon", "2026-08-12", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-13", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-14", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-15", None,    None,    0,   "holiday"),
        ("song_jihoon", "2026-08-18", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-19", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-20", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-21", "09:10", "18:00", 470, "late"),
        ("song_jihoon", "2026-08-22", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-25", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-26", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-27", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-28", "09:00", "18:00", 480, "normal"),
        ("song_jihoon", "2026-08-29", "09:00", "15:00", 300, "early_leave"),

        ("oh_eunji",    "2026-08-04", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-05", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-06", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-07", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-08", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-11", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-12", "09:25", "18:00", 455, "late"),
        ("oh_eunji",    "2026-08-13", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-14", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-15", None,    None,    0,   "holiday"),
        ("oh_eunji",    "2026-08-18", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-19", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-20", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-21", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-22", None,    None,    0,   "absent"),
        ("oh_eunji",    "2026-08-25", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-26", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-27", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-28", "09:00", "18:00", 480, "normal"),
        ("oh_eunji",    "2026-08-29", "09:00", "18:00", 480, "normal"),

        ("han_dongwoo", "2026-08-04", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-05", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-06", "09:10", "17:30", 440, "late"),
        ("han_dongwoo", "2026-08-07", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-08", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-11", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-12", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-13", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-14", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-15", None,    None,    0,   "holiday"),
        ("han_dongwoo", "2026-08-18", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-19", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-20", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-21", None,    None,    0,   "absent"),
        ("han_dongwoo", "2026-08-22", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-25", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-26", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-27", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-28", "09:00", "17:30", 450, "normal"),
        ("han_dongwoo", "2026-08-29", "09:00", "17:30", 450, "normal"),
        # 9월
        ("kim_sujin",   "2026-09-01", "08:55", "18:05", 490, "normal"),
        ("park_minho",  "2026-09-01", "08:50", "18:00", 490, "normal"),
        ("yun_sera",    "2026-09-01", "08:58", "18:10", 492, "normal"),
        ("song_jihun",  "2026-09-01", "08:45", "18:05", 500, "normal"),
        ("oh_eunji",    "2026-09-01", "08:50", "18:00", 490, "normal"),
        ("lee_jiyoung", "2026-09-01", "09:00", "18:05", 485, "normal"),
        ("jung_wusung", "2026-09-01", "08:48", "18:00", 492, "normal"),
        ("choi_yerin",  "2026-09-01", "09:12", "18:00", 468, "late"),
        ("han_dongwoo", "2026-09-01", "09:00", "17:30", 450, "normal"),
        ("na_hyunwoo",  "2026-09-01", "08:50", "18:00", 490, "normal"),
        ("baek_soyeon", "2026-09-01", "09:08", "18:10", 482, "late"),
    ]

    for username, date, clock_in, clock_out, mins, status in attendance_data:
        eid = worker_ids.get(username)
        if eid is None:
            continue
        exists = c.execute(
            "SELECT id FROM attendance WHERE employee_id=? AND work_date=?",
            (eid, date),
        ).fetchone()
        if exists:
            continue
        c.execute(
            """INSERT INTO attendance (employee_id, work_date, clock_in, clock_out, work_minutes, status)
               VALUES (?,?,?,?,?,?)""",
            (eid, date, clock_in, clock_out, mins, status),
        )

    print("  출근 기록 시드 완료")

    conn.commit()

    # 급여명세서
    c.execute("""
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

    import random
    random.seed(42)

    disability_allowances = {
        "na_hyunwoo":  250000,
        "baek_soyeon": 380000,
        "kim_sujin":   300000,
        "park_minho":  400000,
        "yoon_sera":   350000,
        "song_jihoon": 220000,
        "oh_eunji":    310000,
        "lee_jiyoung": 400000,
        "jung_wusung": 200000,
        "choi_yerin":  280000,
        "han_dongwoo": 360000,
    }

    overtime_pool = [0, 0, 0, 50000, 100000, 150000, 200000]

    for username, eid in worker_ids.items():
        da = disability_allowances.get(username, 300000)
        for month in range(1, 9):
            ot = random.choice(overtime_pool)
            base = 2060740
            meal = 100000
            gross = base + ot + da + meal

            pension = round(base * 0.045)
            health = round(base * 0.03545)
            emp_ins = round(base * 0.009)
            income_tax = round(gross * 0.006)
            resident_tax = round(income_tax * 0.1)
            total_ded = pension + health + emp_ins + income_tax + resident_tax
            net = gross - total_ded

            pay_date = f"2026-{month:02d}-25"

            exists = c.execute(
                "SELECT id FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=?",
                (eid, 2026, month),
            ).fetchone()
            if exists:
                continue
            c.execute(
                """INSERT INTO payslips
                   (employee_id, pay_year, pay_month, base_salary, overtime_pay,
                    disability_allowance, meal_allowance, gross_pay,
                    income_tax, resident_tax, national_pension, health_insurance,
                    employment_insurance, total_deduction, net_pay, pay_date)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (eid, 2026, month, base, ot, da, meal, gross,
                 income_tax, resident_tax, pension, health, emp_ins,
                 total_ded, net, pay_date),
            )

    print("  급여명세서 시드 완료")

    conn.commit()

    # 증명서 신청 내역
    c.execute("""
        CREATE TABLE IF NOT EXISTS certificate_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            cert_type TEXT NOT NULL,
            purpose TEXT,
            status TEXT DEFAULT 'completed',
            requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            cert_number TEXT
        )
    """)

    cert_seeds = [
        ("kim_sujin",   "재직증명서", "은행제출용",  "completed", "2026-06-10 09:00:00", "2026-06-10 09:00:00"),
        ("kim_sujin",   "소득금액증명", "관공서제출용", "completed", "2026-07-02 10:30:00", "2026-07-02 10:30:00"),
        ("kim_sujin",   "경력증명서", "개인보관용",  "completed", "2026-08-28 15:00:00", "2026-08-28 15:00:00"),
        ("park_minho",  "재직증명서", "은행제출용",  "completed", "2026-05-20 08:00:00", "2026-05-20 08:00:00"),
        ("park_minho",  "재직증명서", "관공서제출용", "completed", "2026-08-29 09:30:00", "2026-08-29 09:30:00"),
        ("na_hyunwoo",  "소득금액증명", "은행제출용",  "completed", "2026-07-15 11:00:00", "2026-07-15 11:00:00"),
        ("na_hyunwoo",  "경력증명서", "기타",       "completed", "2026-08-10 14:00:00", "2026-08-10 14:00:00"),
        ("baek_soyeon", "재직증명서", "개인보관용",  "completed", "2026-08-30 10:00:00", "2026-08-30 10:00:00"),
        ("lee_jiyoung", "경력증명서", "관공서제출용", "completed", "2026-08-01 09:00:00", "2026-08-01 09:00:00"),
        ("jung_wusung", "재직증명서", "은행제출용",  "completed", "2026-08-31 08:30:00", "2026-08-31 08:30:00"),
    ]

    cert_seq = 0
    for username, cert_type, purpose, status, requested_at, completed_at in cert_seeds:
        eid = worker_ids.get(username)
        if not eid:
            continue
        exists = c.execute(
            "SELECT id FROM certificate_requests WHERE employee_id=? AND cert_type=? AND requested_at=?",
            (eid, cert_type, requested_at),
        ).fetchone()
        if exists:
            print(f"  증명서 이미 있음 (skip): {username} {cert_type}")
            continue
        cert_seq += 1
        cert_number = f"CERT-{requested_at[:10].replace('-','')}-{cert_seq:04d}"
        c.execute(
            """INSERT INTO certificate_requests (employee_id, cert_type, purpose, status, requested_at, completed_at, cert_number)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (eid, cert_type, purpose, status, requested_at, completed_at, cert_number),
        )
        print(f"  증명서 발급: {username} {cert_type} ({cert_number})")

    print("  증명서 시드 완료")

    conn.commit()
    conn.close()
    print("\n완료.")


if __name__ == "__main__":
    run()

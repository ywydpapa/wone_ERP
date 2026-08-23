# 불리언 필드: -1 = 미확인, 0 = 불가, 1 = 가능

CREATE_CAPABILITY_PROFILES = """
CREATE TABLE IF NOT EXISTS capability_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    effective_date TEXT NOT NULL DEFAULT (date('now','localtime')),

    hand_left TEXT NOT NULL DEFAULT 'unknown'
        CHECK(hand_left IN ('unable','gross_only','precise','unknown')),
    hand_right TEXT NOT NULL DEFAULT 'unknown'
        CHECK(hand_right IN ('unable','gross_only','precise','unknown')),
    arm_left TEXT NOT NULL DEFAULT 'unknown'
        CHECK(arm_left IN ('unable','limited','full','unknown')),
    arm_right TEXT NOT NULL DEFAULT 'unknown'
        CHECK(arm_right IN ('unable','limited','full','unknown')),
    neck TEXT NOT NULL DEFAULT 'unknown'
        CHECK(neck IN ('unable','limited','full','unknown')),
    foot_left TEXT NOT NULL DEFAULT 'unknown'
        CHECK(foot_left IN ('unable','limited','full','unknown')),
    foot_right TEXT NOT NULL DEFAULT 'unknown'
        CHECK(foot_right IN ('unable','limited','full','unknown')),
    posture_maintenance INTEGER NOT NULL DEFAULT -1,

    vision TEXT NOT NULL DEFAULT 'unknown'
        CHECK(vision IN ('blind','low_vision','corrected','normal','unknown')),
    hearing TEXT NOT NULL DEFAULT 'unknown'
        CHECK(hearing IN ('deaf','hard_of_hearing','aided','normal','unknown')),
    eye_movement INTEGER NOT NULL DEFAULT -1,
    eyelid_control INTEGER NOT NULL DEFAULT -1,

    speech TEXT NOT NULL DEFAULT 'unknown'
        CHECK(speech IN ('unable','unclear_correctable','capable','unknown')),
    breath_control INTEGER NOT NULL DEFAULT -1,

    reading_level TEXT NOT NULL DEFAULT 'unknown'
        CHECK(reading_level IN ('unable','basic','intermediate','advanced','unknown')),
    sustained_focus INTEGER NOT NULL DEFAULT -1,
    memory_aid_needed INTEGER NOT NULL DEFAULT -1,

    continuous_work_minutes INTEGER DEFAULT NULL,
    fatigue_pattern TEXT DEFAULT '',
    posture_change_interval INTEGER DEFAULT NULL,

    -- Tier 2 overrides (preferred input methods, JSON array string)
    input_overrides TEXT DEFAULT '',

    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (employee_id) REFERENCES employees(id)
)
"""


def up(conn):
    conn.execute(CREATE_CAPABILITY_PROFILES)
    conn.commit()

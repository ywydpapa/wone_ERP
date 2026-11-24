-- ============================================================================
-- WONE ERP MariaDB DDL Schema
-- Generated automatically from latest SQLite migrations (120 versions)
-- Character Set: utf8mb4 / Collation: utf8mb4_unicode_ci
-- ============================================================================

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `accommodation_requests`;
CREATE TABLE `accommodation_requests` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `employee_id` BIGINT NOT NULL,
    `category` VARCHAR(255) NOT NULL,
    `title` VARCHAR(255) NOT NULL,
    `description` TEXT,
    `urgency` VARCHAR(255) NOT NULL DEFAULT 'normal',
    `status` VARCHAR(50) NOT NULL DEFAULT 'pending',
    `reviewed_by` INT,
    `reviewed_at` VARCHAR(255),
    `review_notes` TEXT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `doc_id` BIGINT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `accounts`;
CREATE TABLE `accounts` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL DEFAULT 0,
    `code` VARCHAR(50) NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `category` VARCHAR(255) NOT NULL,
    `is_debit` TINYINT(1) DEFAULT 1,
    `parent_code` VARCHAR(255) DEFAULT '',
    `is_active` TINYINT(1) DEFAULT 1,
    `req_partner` INT DEFAULT 0,
    `req_dept` INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `accrual_posts`;
CREATE TABLE `accrual_posts` (
    `accrual_id` BIGINT NOT NULL,
    `ym` VARCHAR(255) NOT NULL,
    `doc_id` BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `accruals`;
CREATE TABLE `accruals` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `kind` VARCHAR(255) NOT NULL,
    `expense_code` VARCHAR(255) NOT NULL,
    `amount` INT NOT NULL,
    `start_ym` VARCHAR(255) NOT NULL,
    `end_ym` VARCHAR(255) NOT NULL,
    `partner_id` BIGINT,
    `dept` VARCHAR(50) NOT NULL DEFAULT '',
    `memo` TEXT NOT NULL,
    `status` VARCHAR(50) NOT NULL DEFAULT 'active',
    `created_by` INT,
    `created_at` DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `activity_logs`;
CREATE TABLE `activity_logs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `target_type` VARCHAR(255) NOT NULL,
    `target_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL,
    `action` VARCHAR(255) NOT NULL,
    `detail` VARCHAR(255) DEFAULT '',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `approval_deputies`;
CREATE TABLE `approval_deputies` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL,
    `deputy_id` BIGINT NOT NULL,
    `start_date` VARCHAR(20) NOT NULL,
    `end_date` VARCHAR(20) NOT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `approval_lines`;
CREATE TABLE `approval_lines` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `doc_id` BIGINT NOT NULL,
    `step` INT NOT NULL,
    `approver_id` BIGINT NOT NULL,
    `role` VARCHAR(50) NOT NULL,
    `status` VARCHAR(50) DEFAULT 'pending',
    `comment` VARCHAR(255) DEFAULT '',
    `acted_at` DATETIME,
    `acted_by` INT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `approval_presets`;
CREATE TABLE `approval_presets` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL DEFAULT 0,
    `form_key` VARCHAR(255) NOT NULL,
    `lines` TEXT NOT NULL,
    `updated_by` INT,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `attendance`;
CREATE TABLE `attendance` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `employee_id` BIGINT NOT NULL,
    `work_date` VARCHAR(20) NOT NULL,
    `clock_in` VARCHAR(255),
    `clock_out` VARCHAR(255),
    `work_minutes` INT DEFAULT 0,
    `overtime_minutes` INT DEFAULT 0,
    `break_minutes` INT DEFAULT 0,
    `status` VARCHAR(50) DEFAULT 'normal',
    `notes` TEXT,
    `appeal` VARCHAR(255),
    `appeal_type` VARCHAR(255),
    `appeal_reason` TEXT,
    `appeal_file` VARCHAR(255) DEFAULT '',
    `appeal_reviewed_by` INT,
    `appeal_at` VARCHAR(255),
    `appeal_reject_reason` TEXT,
    `disability_related` INT DEFAULT 0,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `appeal_desired_clock_in` VARCHAR(255),
    `appeal_desired_clock_out` VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `attendance_closing_logs`;
CREATE TABLE `attendance_closing_logs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `closing_id` BIGINT NOT NULL,
    `action` VARCHAR(255) NOT NULL,
    `performed_by` INT NOT NULL,
    `reason` TEXT,
    `detail` VARCHAR(255) DEFAULT '',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `attendance_closings`;
CREATE TABLE `attendance_closings` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `year` INT NOT NULL,
    `month` INT NOT NULL,
    `company_id` BIGINT,
    `status` VARCHAR(50) NOT NULL DEFAULT 'open',
    `closed_by` INT,
    `closed_at` VARCHAR(255),
    `reopened_by` INT,
    `reopened_at` VARCHAR(255),
    `reopen_reason` TEXT,
    `absent_count` INT DEFAULT 0,
    `notes` TEXT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `attendance_logs`;
CREATE TABLE `attendance_logs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `attendance_id` BIGINT NOT NULL,
    `changed_by` INT NOT NULL,
    `field` VARCHAR(255) NOT NULL,
    `old_value` VARCHAR(255),
    `new_value` VARCHAR(255),
    `reason` TEXT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `audit_logs`;
CREATE TABLE `audit_logs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `at` VARCHAR(255) NOT NULL,
    `user_id` BIGINT,
    `user_name` VARCHAR(255),
    `role` VARCHAR(50),
    `company_id` BIGINT,
    `action` VARCHAR(255) NOT NULL,
    `target_type` VARCHAR(255),
    `target_id` BIGINT,
    `summary` VARCHAR(255) NOT NULL DEFAULT '',
    `detail` VARCHAR(255),
    `ip` VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `bank_accounts`;
CREATE TABLE `bank_accounts` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL DEFAULT 0,
    `bank` VARCHAR(255) NOT NULL,
    `account_no` VARCHAR(255) NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `account_code` VARCHAR(50) NOT NULL DEFAULT '103',
    `is_active` TINYINT(1) DEFAULT 1,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `import_preset` VARCHAR(255),
    `column_map` VARCHAR(255),
    `partner_id` BIGINT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `bank_txns`;
CREATE TABLE `bank_txns` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `bank_account_id` BIGINT NOT NULL,
    `txn_at` VARCHAR(255) NOT NULL,
    `memo` TEXT NOT NULL,
    `counterparty` VARCHAR(255) NOT NULL DEFAULT '',
    `amt_in` INT NOT NULL DEFAULT 0,
    `amt_out` INT NOT NULL DEFAULT 0,
    `balance` INT,
    `hash` VARCHAR(255) NOT NULL,
    `status` VARCHAR(50) NOT NULL DEFAULT '미처리',
    `doc_id` BIGINT,
    `settlement_id` BIGINT,
    `uploaded_by` INT,
    `uploaded_at` VARCHAR(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `bom_headers`;
CREATE TABLE `bom_headers` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `product_id` BIGINT NOT NULL,
    `bom_version` VARCHAR(255) DEFAULT '1.0',
    `effective_date` VARCHAR(20),
    `is_active` TINYINT(1) DEFAULT 1,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `created_by` INT,
    `task_id` BIGINT,
    `company_id` BIGINT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `bom_lines`;
CREATE TABLE `bom_lines` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `bom_id` BIGINT NOT NULL,
    `component_id` BIGINT NOT NULL,
    `quantity` DECIMAL(15, 2) NOT NULL,
    `unit` VARCHAR(255) DEFAULT 'EA',
    `process_step` VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `bookmarks`;
CREATE TABLE `bookmarks` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `post_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `budget_cfg`;
CREATE TABLE `budget_cfg` (
    `company_id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `period` VARCHAR(255) NOT NULL DEFAULT 'year',
    `warn_pct` INT NOT NULL DEFAULT 90,
    `notify_pct` INT NOT NULL DEFAULT 95,
    `block_pct` INT NOT NULL DEFAULT 100
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `budget_changes`;
CREATE TABLE `budget_changes` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `dept` VARCHAR(50) NOT NULL DEFAULT '',
    `account_code` VARCHAR(50) NOT NULL,
    `year` INT NOT NULL,
    `month` INT NOT NULL,
    `kind` VARCHAR(255) NOT NULL,
    `amount` INT NOT NULL,
    `reason` TEXT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `budget_notified`;
CREATE TABLE `budget_notified` (
    `company_id` BIGINT NOT NULL,
    `dept` VARCHAR(50) NOT NULL DEFAULT '',
    `account_code` VARCHAR(50) NOT NULL,
    `year` INT NOT NULL,
    `month` INT NOT NULL,
    `notified_at` VARCHAR(255) DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`company_id`, `dept`, `account_code`, `year`, `month`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `budgets`;
CREATE TABLE `budgets` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL DEFAULT 0,
    `dept` VARCHAR(50) NOT NULL DEFAULT '',
    `account_code` VARCHAR(50) NOT NULL,
    `year` INT NOT NULL,
    `month` INT NOT NULL,
    `amount` INT NOT NULL DEFAULT 0,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `capability_profiles`;
CREATE TABLE `capability_profiles` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `employee_id` BIGINT NOT NULL,
    `effective_date` VARCHAR(20) NOT NULL,
    `hand_left` VARCHAR(255) NOT NULL DEFAULT 'unknown',
    `hand_right` VARCHAR(255) NOT NULL DEFAULT 'unknown',
    `arm_left` VARCHAR(255) NOT NULL DEFAULT 'unknown',
    `arm_right` VARCHAR(255) NOT NULL DEFAULT 'unknown',
    `neck` VARCHAR(255) NOT NULL DEFAULT 'unknown',
    `foot_left` VARCHAR(255) NOT NULL DEFAULT 'unknown',
    `foot_right` VARCHAR(255) NOT NULL DEFAULT 'unknown',
    `posture_maintenance` INT NOT NULL DEFAULT -1,
    `vision` VARCHAR(255) NOT NULL DEFAULT 'unknown',
    `hearing` VARCHAR(255) NOT NULL DEFAULT 'unknown',
    `eye_movement` INT NOT NULL DEFAULT -1,
    `eyelid_control` BIGINT NOT NULL DEFAULT -1,
    `speech` VARCHAR(255) NOT NULL DEFAULT 'unknown',
    `breath_control` INT NOT NULL DEFAULT -1,
    `reading_level` VARCHAR(255) NOT NULL DEFAULT 'unknown',
    `sustained_focus` INT NOT NULL DEFAULT -1,
    `memory_aid_needed` BIGINT NOT NULL DEFAULT -1,
    `continuous_work_minutes` INT DEFAULT NULL,
    `fatigue_pattern` VARCHAR(255) DEFAULT '',
    `posture_change_interval` INT DEFAULT NULL,
    `input_overrides` VARCHAR(255) DEFAULT '',
    `notes` TEXT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `card_txns`;
CREATE TABLE `card_txns` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `card_no` VARCHAR(255) DEFAULT '',
    `approve_date` VARCHAR(20) NOT NULL,
    `approval_no` VARCHAR(255) NOT NULL,
    `merchant` VARCHAR(255) DEFAULT '',
    `merchant_biz_no` VARCHAR(255) DEFAULT '',
    `supply_amt` INT NOT NULL DEFAULT 0,
    `vat` INT NOT NULL DEFAULT 0,
    `total` INT NOT NULL DEFAULT 0,
    `status` VARCHAR(50) NOT NULL DEFAULT 'new',
    `tax_invoice_id` BIGINT,
    `doc_id` BIGINT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `cardnews_projects`;
CREATE TABLE `cardnews_projects` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `title` VARCHAR(255) NOT NULL DEFAULT '새 카드뉴스',
    `aspect_ratio` VARCHAR(255) NOT NULL DEFAULT '1:1',
    `width` BIGINT NOT NULL DEFAULT 1080,
    `height` INT NOT NULL DEFAULT 1080,
    `slides_json` TEXT NOT NULL,
    `thumbnail` VARCHAR(255) DEFAULT '',
    `created_by` INT,
    `created_by_name` VARCHAR(255) DEFAULT '',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `certificate_requests`;
CREATE TABLE `certificate_requests` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `employee_id` BIGINT NOT NULL,
    `cert_type` VARCHAR(255) NOT NULL,
    `purpose` VARCHAR(255),
    `status` VARCHAR(50) DEFAULT 'pending',
    `requested_at` VARCHAR(255) DEFAULT CURRENT_TIMESTAMP,
    `cert_number` VARCHAR(255),
    `completed_at` VARCHAR(255),
    `issued_by` INT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `client_companies`;
CREATE TABLE `client_companies` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(100) NOT NULL,
    `business_no` VARCHAR(255),
    `contact_name` VARCHAR(255) DEFAULT '',
    `contact_phone` VARCHAR(255) DEFAULT '',
    `contact_email` VARCHAR(255) DEFAULT '',
    `contract_start` VARCHAR(255),
    `contract_end` VARCHAR(255),
    `status` VARCHAR(50) DEFAULT 'active',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `representative` VARCHAR(255) DEFAULT '',
    `address` VARCHAR(255) DEFAULT '',
    `employee_count` INT DEFAULT 0,
    `contract_amount` INT DEFAULT 0,
    `contract_content` TEXT,
    `logo_file` VARCHAR(255) DEFAULT '',
    `appeal_guide` VARCHAR(255) DEFAULT '',
    `appeal_types` VARCHAR(255) DEFAULT '["transit","medical","accident","disability","family","etc"]',
    `appeal_require_file` INT DEFAULT 0,
    `pay_day` INT DEFAULT 25,
    `biz_type` VARCHAR(255) DEFAULT '',
    `biz_item` VARCHAR(255) DEFAULT '',
    `payroll_delegated` INT DEFAULT 0,
    `credit_limit_mode` VARCHAR(255) DEFAULT 'off',
    `credit_days_mode` VARCHAR(255) DEFAULT 'off',
    `partner_alerts` VARCHAR(255) DEFAULT '',
    `sector` VARCHAR(255) NOT NULL DEFAULT '민간',
    `sick_doc_days` INT NOT NULL DEFAULT 3,
    `export_set` VARCHAR(255) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `client_users`;
CREATE TABLE `client_users` (
    `user_id` BIGINT NOT NULL,
    `company_id` BIGINT NOT NULL,
    `client_role` VARCHAR(255) DEFAULT 'all',
    PRIMARY KEY (`user_id`, `company_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `comments`;
CREATE TABLE `comments` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `post_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL,
    `author` VARCHAR(255) NOT NULL DEFAULT '',
    `content` TEXT NOT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `crm_activities`;
CREATE TABLE `crm_activities` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `partner_id` BIGINT,
    `lead_id` BIGINT,
    `opp_id` BIGINT,
    `kind` VARCHAR(255) NOT NULL DEFAULT 'call',
    `act_date` VARCHAR(20) NOT NULL,
    `subject` VARCHAR(255) NOT NULL,
    `content` TEXT,
    `rep_id` BIGINT,
    `next_date` VARCHAR(20) DEFAULT '',
    `next_action` VARCHAR(255) DEFAULT '',
    `next_done` INT DEFAULT 0,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `contact_id` BIGINT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `crm_leads`;
CREATE TABLE `crm_leads` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `contact_name` VARCHAR(255) DEFAULT '',
    `phone` VARCHAR(100) DEFAULT '',
    `email` VARCHAR(100) DEFAULT '',
    `biz_no` VARCHAR(255) DEFAULT '',
    `address` VARCHAR(255) DEFAULT '',
    `source` VARCHAR(255) DEFAULT '',
    `status` VARCHAR(50) NOT NULL DEFAULT 'new',
    `rep_id` BIGINT,
    `partner_id` BIGINT,
    `notes` TEXT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `crm_opps`;
CREATE TABLE `crm_opps` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `title` VARCHAR(255) NOT NULL,
    `partner_id` BIGINT,
    `lead_id` BIGINT,
    `stage` VARCHAR(255) NOT NULL DEFAULT 'found',
    `amount` INT NOT NULL DEFAULT 0,
    `close_date` VARCHAR(20) DEFAULT '',
    `rep_id` BIGINT,
    `quote_id` BIGINT,
    `lost_reason` TEXT,
    `notes` TEXT,
    `closed_at` VARCHAR(255) DEFAULT '',
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `dashboard_prefs`;
CREATE TABLE `dashboard_prefs` (
    `user_id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `widgets` VARCHAR(255) NOT NULL DEFAULT '[]',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `cols` INT DEFAULT 4
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `depts`;
CREATE TABLE `depts` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `code` VARCHAR(50) NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `sort` INT DEFAULT 0,
    `is_active` TINYINT(1) DEFAULT 1,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `disability_awareness_attendees`;
CREATE TABLE `disability_awareness_attendees` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `training_id` BIGINT NOT NULL,
    `employee_id` BIGINT NOT NULL,
    `completed` INT NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `disability_awareness_trainings`;
CREATE TABLE `disability_awareness_trainings` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT,
    `held_date` VARCHAR(20) NOT NULL,
    `method` VARCHAR(255) NOT NULL,
    `instructor` VARCHAR(255) DEFAULT '',
    `content` TEXT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `doc_history`;
CREATE TABLE `doc_history` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `doc_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL,
    `user_name` VARCHAR(255) NOT NULL DEFAULT '',
    `action` VARCHAR(255) NOT NULL,
    `comment` VARCHAR(255) DEFAULT '',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `document_types`;
CREATE TABLE `document_types` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `code` VARCHAR(50) NOT NULL,
    `label` VARCHAR(255) NOT NULL,
    `category` VARCHAR(255) DEFAULT '공통',
    `form_schema` VARCHAR(255) DEFAULT '{}',
    `doc_number_prefix` VARCHAR(255) DEFAULT 'DOC',
    `is_active` TINYINT(1) DEFAULT 1,
    `name` VARCHAR(100) DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `employee_files`;
CREATE TABLE `employee_files` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT,
    `employee_id` BIGINT NOT NULL,
    `kind` VARCHAR(255) NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `path` VARCHAR(255) NOT NULL,
    `uploaded_by` INT,
    `uploaded_at` VARCHAR(255) DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `employees`;
CREATE TABLE `employees` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT,
    `name` VARCHAR(100) NOT NULL,
    `employee_no` VARCHAR(255),
    `dept` VARCHAR(50) NOT NULL DEFAULT '경영지원팀',
    `position` VARCHAR(255) NOT NULL DEFAULT '사원',
    `hire_date` VARCHAR(20),
    `status` VARCHAR(50) NOT NULL DEFAULT 'active',
    `disability_type` VARCHAR(255) DEFAULT '',
    `disability_grade` VARCHAR(255) DEFAULT '',
    `emergency_contact` VARCHAR(255) DEFAULT '',
    `emergency_phone` VARCHAR(255) DEFAULT '',
    `notes` TEXT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `company_id` BIGINT,
    `bank_name` VARCHAR(255),
    `bank_account` VARCHAR(255),
    `address` VARCHAR(255),
    `birth_date` VARCHAR(20),
    `resident_no` VARCHAR(100) DEFAULT '',
    `job_title` VARCHAR(255) DEFAULT '',
    `monthly_work_hours` INT DEFAULT 0,
    `employment_insurance` INT DEFAULT 1,
    `disability_cert_file` VARCHAR(255) DEFAULT '',
    `phone` VARCHAR(100) DEFAULT '',
    `email` VARCHAR(100) DEFAULT '',
    `gender` VARCHAR(255) DEFAULT '',
    `base_salary` INT NOT NULL DEFAULT 0,
    `tax_dependent_count` INT DEFAULT 1,
    `resign_date` VARCHAR(20),
    `resign_reason` TEXT,
    `tax_child_count` INT DEFAULT 0,
    `tax_rate` INT DEFAULT 100,
    `renew_date` VARCHAR(20),
    `contract_end` VARCHAR(255),
    `career` VARCHAR(255),
    `education` VARCHAR(255),
    `military` VARCHAR(255),
    `license` VARCHAR(255),
    `training` VARCHAR(255),
    `disability_class` VARCHAR(255),
    `veteran_grade` VARCHAR(255),
    `disability_date` VARCHAR(20),
    `job_code` VARCHAR(50)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `erp_activity_log`;
CREATE TABLE `erp_activity_log` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL,
    `action` VARCHAR(255) NOT NULL,
    `module` VARCHAR(255) NOT NULL,
    `target_id` BIGINT NOT NULL,
    `doc_number` VARCHAR(255),
    `summary` VARCHAR(255) NOT NULL,
    `created_at` DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `erp_docs`;
CREATE TABLE `erp_docs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL,
    `doc_type` VARCHAR(255) NOT NULL DEFAULT 'draft',
    `title` VARCHAR(255) NOT NULL DEFAULT '',
    `content` TEXT NOT NULL,
    `status` VARCHAR(50) NOT NULL DEFAULT 'draft',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `doc_number` VARCHAR(255) DEFAULT '',
    `dept` VARCHAR(50) DEFAULT '',
    `attachment` VARCHAR(255) DEFAULT '',
    `visibility` VARCHAR(255) DEFAULT '공개',
    `retention_period` VARCHAR(255) DEFAULT '3년',
    `effective_date` VARCHAR(20) DEFAULT '',
    `approved_by` INT,
    `approved_at` VARCHAR(255),
    `reject_reason` TEXT,
    `slip_type` VARCHAR(255) DEFAULT '',
    `slip_date` VARCHAR(20) DEFAULT '',
    `slip_total` INT DEFAULT 0,
    `extra_fields` VARCHAR(255) DEFAULT '{}',
    `due_label` VARCHAR(255) DEFAULT '',
    `doc_type_id` BIGINT,
    `template_id` BIGINT,
    `evidence_type` VARCHAR(255) DEFAULT '',
    `evidence_no` VARCHAR(255) DEFAULT '',
    `project_code` VARCHAR(255) DEFAULT '',
    `task_id` BIGINT,
    `payslip_id` BIGINT DEFAULT NULL,
    `company_id` BIGINT DEFAULT 0,
    `slip_no` VARCHAR(255),
    `source_type` VARCHAR(255) DEFAULT 'manual',
    `source_id` BIGINT,
    `reversal_of` INT,
    `posted_at` VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `export_logs`;
CREATE TABLE `export_logs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL,
    `work_request_id` BIGINT NOT NULL,
    `kind` VARCHAR(255) NOT NULL DEFAULT 'data',
    `template_id` BIGINT,
    `row_count` INT DEFAULT 0,
    `file_name` VARCHAR(255) DEFAULT '',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `export_templates`;
CREATE TABLE `export_templates` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `module` VARCHAR(255) NOT NULL,
    `name` VARCHAR(100) NOT NULL DEFAULT '기본',
    `columns` VARCHAR(255) NOT NULL DEFAULT '[]',
    `file_format` VARCHAR(255) NOT NULL DEFAULT 'xlsx',
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `fa_capex`;
CREATE TABLE `fa_capex` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `asset_id` BIGINT NOT NULL,
    `date` VARCHAR(255) NOT NULL,
    `amount` INT NOT NULL,
    `memo` TEXT NOT NULL,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `fa_depr`;
CREATE TABLE `fa_depr` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `asset_id` BIGINT NOT NULL,
    `year` INT NOT NULL,
    `amount` INT NOT NULL,
    `doc_id` BIGINT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `fi_closings`;
CREATE TABLE `fi_closings` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL DEFAULT 0,
    `year` INT NOT NULL,
    `month` INT NOT NULL,
    `status` VARCHAR(50) NOT NULL DEFAULT 'open',
    `closed_by` INT,
    `closed_at` VARCHAR(255),
    `reopened_by` INT,
    `reopened_at` VARCHAR(255),
    `reopen_reason` TEXT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `fiscal_closings`;
CREATE TABLE `fiscal_closings` (
    `company_id` BIGINT NOT NULL,
    `year` INT NOT NULL,
    `status` VARCHAR(50) NOT NULL DEFAULT 'closed',
    `closed_by` INT,
    `closed_at` VARCHAR(255),
    `reopened_by` INT,
    `reopened_at` VARCHAR(255),
    `reopen_reason` TEXT,
    PRIMARY KEY (`company_id`, `year`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `fixed_assets`;
CREATE TABLE `fixed_assets` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL DEFAULT 0,
    `code` VARCHAR(50) NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `account_code` VARCHAR(50) NOT NULL,
    `acq_date` VARCHAR(20) NOT NULL,
    `acq_cost` INT NOT NULL,
    `life_years` INT NOT NULL,
    `method` VARCHAR(255) NOT NULL DEFAULT '정액법',
    `open_accum` INT NOT NULL DEFAULT 0,
    `open_year` INT NOT NULL,
    `dept` VARCHAR(50) DEFAULT '',
    `status` VARCHAR(50) NOT NULL DEFAULT 'active',
    `disposed_date` VARCHAR(20),
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `form_templates`;
CREATE TABLE `form_templates` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `category` VARCHAR(255) DEFAULT '일반',
    `fields` VARCHAR(255) DEFAULT '[]',
    `is_active` TINYINT(1) DEFAULT 1,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `goods_receipts`;
CREATE TABLE `goods_receipts` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `gr_number` VARCHAR(255) NOT NULL,
    `po_id` BIGINT,
    `warehouse_id` BIGINT,
    `receipt_date` VARCHAR(20) NOT NULL,
    `status` VARCHAR(50) DEFAULT 'draft',
    `notes` TEXT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `task_id` BIGINT,
    `company_id` BIGINT,
    `kind` VARCHAR(255) NOT NULL DEFAULT '입고',
    `canceled_at` VARCHAR(255),
    `qc_status` VARCHAR(255) NOT NULL DEFAULT '',
    `inspect_memo` TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `gr_lines`;
CREATE TABLE `gr_lines` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `gr_id` BIGINT NOT NULL,
    `po_line_id` BIGINT,
    `item_id` BIGINT NOT NULL,
    `received_qty` INT NOT NULL,
    `defective_qty` INT DEFAULT 0,
    `orig_line_id` BIGINT,
    `inspect_pass_qty` INT NOT NULL DEFAULT 0,
    `inspect_fail_qty` INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `help_requests`;
CREATE TABLE `help_requests` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `task_id` BIGINT,
    `work_request_id` BIGINT,
    `employee_id` BIGINT NOT NULL,
    `reason` TEXT,
    `status` VARCHAR(50) DEFAULT 'open',
    `resolved_by` INT,
    `resolve_note` TEXT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `resolved_at` VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `holidays`;
CREATE TABLE `holidays` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `year` INT NOT NULL,
    `date` VARCHAR(255) NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `type` VARCHAR(255) NOT NULL DEFAULT 'public'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `hr_appointments`;
CREATE TABLE `hr_appointments` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT,
    `employee_id` BIGINT NOT NULL,
    `kind` VARCHAR(255) NOT NULL,
    `from_val` VARCHAR(255) DEFAULT '',
    `to_val` VARCHAR(255) DEFAULT '',
    `effective_date` VARCHAR(20) NOT NULL,
    `memo` TEXT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `insurance_rates`;
CREATE TABLE `insurance_rates` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `rate_key` VARCHAR(255) NOT NULL,
    `rate_value` DECIMAL(15, 2) NOT NULL,
    `effective_date` VARCHAR(20) NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `items`;
CREATE TABLE `items` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL DEFAULT 0,
    `item_code` VARCHAR(255) NOT NULL,
    `item_name` VARCHAR(255) NOT NULL,
    `item_type` VARCHAR(255) DEFAULT 'material',
    `unit` VARCHAR(255) DEFAULT 'EA',
    `unit_price` INT DEFAULT 0,
    `safety_stock` INT DEFAULT 0,
    `category` VARCHAR(255) DEFAULT '',
    `is_active` TINYINT(1) DEFAULT 1,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `created_by` INT,
    `task_id` BIGINT,
    `stock_amt` INT NOT NULL DEFAULT 0,
    `purch_group` VARCHAR(255) NOT NULL DEFAULT '',
    `partner_id` BIGINT,
    `lead_days` INT NOT NULL DEFAULT 0,
    `moq` INT NOT NULL DEFAULT 0,
    `order_unit` INT NOT NULL DEFAULT 1,
    `reorder_pt` INT NOT NULL DEFAULT 0,
    `is_stock` TINYINT(1) NOT NULL DEFAULT 1,
    `account_code` VARCHAR(50) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `jobs`;
CREATE TABLE `jobs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT,
    `work_date` VARCHAR(20),
    `category` VARCHAR(255),
    `title` VARCHAR(255) NOT NULL,
    `details` VARCHAR(255),
    `issues` VARCHAR(255),
    `dept` VARCHAR(50) DEFAULT '공통 업무',
    `due_label` VARCHAR(255) DEFAULT '',
    `status` VARCHAR(50) DEFAULT 'progress',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `start_time` VARCHAR(255) DEFAULT '',
    `end_time` VARCHAR(255) DEFAULT '',
    `work_minutes` INT DEFAULT 0,
    `volume` INT DEFAULT 0,
    `volume_unit` VARCHAR(255) DEFAULT '',
    `review_status` VARCHAR(255) DEFAULT 'none',
    `reviewer_id` BIGINT,
    `review_comment` VARCHAR(255) DEFAULT '',
    `reviewed_at` VARCHAR(255),
    `task_id` BIGINT,
    `attachment` VARCHAR(255) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `labor_contracts`;
CREATE TABLE `labor_contracts` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT,
    `employee_id` BIGINT NOT NULL,
    `version` INT NOT NULL DEFAULT 1,
    `prev_id` BIGINT,
    `kind` VARCHAR(255) NOT NULL DEFAULT '일반',
    `has_term` INT NOT NULL DEFAULT 1,
    `start_date` VARCHAR(20) NOT NULL,
    `end_date` VARCHAR(20) DEFAULT '',
    `place` VARCHAR(255) NOT NULL DEFAULT '',
    `duty` VARCHAR(255) NOT NULL DEFAULT '',
    `work_days` VARCHAR(255) DEFAULT '',
    `work_start` VARCHAR(255) DEFAULT '',
    `work_end` VARCHAR(255) DEFAULT '',
    `break_min` INT DEFAULT 60,
    `weekly_hours` DECIMAL(15, 2) DEFAULT 0,
    `daily_hours_json` TEXT,
    `holidays` VARCHAR(255) DEFAULT '매주 일요일(주휴일)',
    `wage_type` VARCHAR(255) NOT NULL DEFAULT '월급',
    `base_pay` INT NOT NULL DEFAULT 0,
    `allowances_json` TEXT,
    `pay_day` VARCHAR(255) DEFAULT '매월 25일',
    `pay_method` VARCHAR(255) DEFAULT '근로자 명의 계좌로 지급',
    `annual_leave` VARCHAR(255) DEFAULT '근로기준법 제60조에 따라 부여',
    `insurance` VARCHAR(255) DEFAULT '고용보험,산재보험,국민연금,건강보험',
    `etc_terms` VARCHAR(255) DEFAULT '',
    `status` VARCHAR(50) NOT NULL DEFAULT 'draft',
    `body_html` TEXT,
    `body_hash` TEXT,
    `employer_signed_by` INT,
    `employer_signed_at` VARCHAR(255),
    `employer_sign_ip` VARCHAR(255),
    `worker_signed_at` VARCHAR(255),
    `worker_sign_ip` VARCHAR(255),
    `worker_sign_name` VARCHAR(255),
    `delivered_at` VARCHAR(255),
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `leave_accruals`;
CREATE TABLE `leave_accruals` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `employee_id` BIGINT NOT NULL,
    `accrual_year` INT NOT NULL,
    `granted` INT NOT NULL,
    `used` DECIMAL(15, 2) NOT NULL DEFAULT 0,
    `basis` VARCHAR(255) NOT NULL DEFAULT 'auto',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `leave_requests`;
CREATE TABLE `leave_requests` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `employee_id` BIGINT NOT NULL,
    `leave_type` VARCHAR(255) NOT NULL,
    `start_date` VARCHAR(20) NOT NULL,
    `end_date` VARCHAR(20) NOT NULL,
    `days` DECIMAL(15, 2) NOT NULL DEFAULT 1,
    `reason` TEXT,
    `status` VARCHAR(50) NOT NULL DEFAULT 'pending',
    `approved_by` INT,
    `approved_at` VARCHAR(255),
    `reject_reason` TEXT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `attachment` VARCHAR(255),
    `half_day_period` VARCHAR(255),
    `doc_id` BIGINT,
    `cancel_doc_id` BIGINT,
    `cancel_reason` TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `login_attempts`;
CREATE TABLE `login_attempts` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(100) NOT NULL,
    `ip` VARCHAR(255),
    `ok` INT NOT NULL,
    `at` VARCHAR(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `memo_codes`;
CREATE TABLE `memo_codes` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL DEFAULT 0,
    `code` VARCHAR(50) NOT NULL,
    `text` VARCHAR(255) NOT NULL,
    `account_code` VARCHAR(50),
    `is_active` TINYINT(1) DEFAULT 1,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `menu_favs`;
CREATE TABLE `menu_favs` (
    `user_id` BIGINT NOT NULL,
    `href` VARCHAR(255) NOT NULL,
    `label` VARCHAR(255) NOT NULL,
    `sort` INT NOT NULL DEFAULT 0,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`user_id`, `href`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `menu_prefs`;
CREATE TABLE `menu_prefs` (
    `user_id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `hidden` VARCHAR(255) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `messages`;
CREATE TABLE `messages` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT,
    `sender` VARCHAR(255) NOT NULL,
    `recipient` VARCHAR(255) DEFAULT '',
    `body` TEXT NOT NULL,
    `time_label` VARCHAR(255) DEFAULT '',
    `is_read` TINYINT(1) DEFAULT 0,
    `direction` VARCHAR(255) DEFAULT 'in',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `monthly_reports`;
CREATE TABLE `monthly_reports` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `year` INT NOT NULL,
    `month` INT NOT NULL,
    `data` VARCHAR(255) NOT NULL DEFAULT '{}',
    `status` VARCHAR(50) NOT NULL DEFAULT 'draft',
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `notes`;
CREATE TABLE `notes` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `kind` VARCHAR(255) NOT NULL,
    `note_no` TEXT NOT NULL,
    `partner_id` BIGINT NOT NULL,
    `amount` INT NOT NULL,
    `issue_date` VARCHAR(20) NOT NULL,
    `due_date` VARCHAR(20) NOT NULL,
    `bank` VARCHAR(255) DEFAULT '',
    `is_electronic` TINYINT(1) DEFAULT 0,
    `status` VARCHAR(50) NOT NULL,
    `issue_doc_id` BIGINT,
    `close_doc_id` BIGINT,
    `close_date` VARCHAR(20),
    `endorsee_id` BIGINT,
    `memo` TEXT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `notifications`;
CREATE TABLE `notifications` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL,
    `title` VARCHAR(255) NOT NULL,
    `message` VARCHAR(255) DEFAULT '',
    `link` VARCHAR(255) DEFAULT '',
    `is_read` TINYINT(1) DEFAULT 0,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `partner_addrs`;
CREATE TABLE `partner_addrs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `partner_id` BIGINT NOT NULL,
    `name` VARCHAR(100) DEFAULT '',
    `postcode` VARCHAR(255) DEFAULT '',
    `address` VARCHAR(255) NOT NULL,
    `receiver` VARCHAR(255) DEFAULT '',
    `phone` VARCHAR(100) DEFAULT '',
    `is_default` TINYINT(1) DEFAULT 0,
    `sort` INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `partner_banks`;
CREATE TABLE `partner_banks` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `partner_id` BIGINT NOT NULL,
    `bank` VARCHAR(255) NOT NULL,
    `account_no` VARCHAR(255) NOT NULL,
    `holder` VARCHAR(255) DEFAULT '',
    `is_default` TINYINT(1) DEFAULT 0,
    `sort` INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `partner_contacts`;
CREATE TABLE `partner_contacts` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `partner_id` BIGINT NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `dept` VARCHAR(50) DEFAULT '',
    `position` VARCHAR(255) DEFAULT '',
    `phone` VARCHAR(100) DEFAULT '',
    `mobile` VARCHAR(100) DEFAULT '',
    `email` VARCHAR(100) DEFAULT '',
    `sort` INT NOT NULL DEFAULT 0,
    `roles` VARCHAR(255) DEFAULT '',
    `fax` VARCHAR(255) DEFAULT '',
    `birthday` VARCHAR(255) DEFAULT '',
    `memo` TEXT,
    `is_primary` TINYINT(1) DEFAULT 0,
    `is_active` TINYINT(1) DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `partner_fields`;
CREATE TABLE `partner_fields` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `label` VARCHAR(255) NOT NULL,
    `kind` VARCHAR(255) NOT NULL DEFAULT 'text',
    `sort` INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `partner_files`;
CREATE TABLE `partner_files` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `partner_id` BIGINT NOT NULL,
    `kind` VARCHAR(255) NOT NULL,
    `file` VARCHAR(255) NOT NULL,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `partner_grades`;
CREATE TABLE `partner_grades` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `min_sales` INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `partner_groups`;
CREATE TABLE `partner_groups` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `name` VARCHAR(100) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `partner_history`;
CREATE TABLE `partner_history` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `partner_id` BIGINT NOT NULL,
    `field` VARCHAR(255) NOT NULL,
    `old` VARCHAR(255) DEFAULT '',
    `new` VARCHAR(255) DEFAULT '',
    `user_id` BIGINT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `partner_prices`;
CREATE TABLE `partner_prices` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `partner_id` BIGINT NOT NULL,
    `item_id` BIGINT NOT NULL,
    `kind` VARCHAR(255) NOT NULL,
    `price` INT NOT NULL,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `valid_from` VARCHAR(255) NOT NULL DEFAULT '',
    `valid_to` VARCHAR(255) NOT NULL DEFAULT '',
    `lead_days` INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `partners`;
CREATE TABLE `partners` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL DEFAULT 0,
    `code` VARCHAR(50) NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `biz_no` VARCHAR(255) DEFAULT '',
    `representative` VARCHAR(255) DEFAULT '',
    `biz_type` VARCHAR(255) DEFAULT '',
    `biz_item` VARCHAR(255) DEFAULT '',
    `address` VARCHAR(255) DEFAULT '',
    `phone` VARCHAR(100) DEFAULT '',
    `is_active` TINYINT(1) DEFAULT 1,
    `partner_type` VARCHAR(255) DEFAULT 'supplier',
    `contact_name` VARCHAR(255) DEFAULT '',
    `contact_phone` VARCHAR(255) DEFAULT '',
    `contact_email` VARCHAR(255) DEFAULT '',
    `email` VARCHAR(100) DEFAULT '',
    `fax` VARCHAR(255) DEFAULT '',
    `notes` TEXT,
    `created_by` INT,
    `task_id` BIGINT,
    `tax_type` VARCHAR(255) DEFAULT '과세',
    `group_id` BIGINT,
    `sale_pg_id` BIGINT,
    `buy_pg_id` BIGINT,
    `credit_limit` INT DEFAULT 0,
    `credit_days` INT DEFAULT 0,
    `extra` VARCHAR(255) DEFAULT '{}',
    `rep_id` BIGINT,
    `grade_id` BIGINT,
    `grade_fixed` INT DEFAULT 0,
    `kind` VARCHAR(255) DEFAULT 'general',
    `reg_kind` VARCHAR(255) DEFAULT 'biz',
    `biz_status` VARCHAR(255) DEFAULT 'normal',
    `biz_checked_at` VARCHAR(255) DEFAULT '',
    `trade_status` VARCHAR(255) DEFAULT 'active',
    `postcode` VARCHAR(255) DEFAULT '',
    `pay_terms` VARCHAR(255) DEFAULT '',
    `pay_days` INT DEFAULT 0,
    `sub_rep_id` BIGINT,
    `merged_into` INT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `pay_items`;
CREATE TABLE `pay_items` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL DEFAULT 0,
    `code` VARCHAR(50) NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `kind` VARCHAR(255) NOT NULL DEFAULT '지급',
    `taxable` INT NOT NULL DEFAULT 1,
    `tax_free_code` VARCHAR(255) DEFAULT '',
    `tax_free_limit` INT DEFAULT 0,
    `ordinary` INT NOT NULL DEFAULT 0,
    `avg_wage` INT NOT NULL DEFAULT 1,
    `bonus` INT NOT NULL DEFAULT 0,
    `sort` INT NOT NULL DEFAULT 0,
    `active` INT NOT NULL DEFAULT 1,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `payslip_items`;
CREATE TABLE `payslip_items` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `payslip_id` BIGINT NOT NULL,
    `item_id` BIGINT NOT NULL,
    `amount` INT NOT NULL DEFAULT 0,
    `overridden` BIGINT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `payslips`;
CREATE TABLE `payslips` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `employee_id` BIGINT NOT NULL,
    `pay_year` INT NOT NULL,
    `pay_month` INT NOT NULL,
    `gross_pay` INT NOT NULL,
    `income_tax` INT DEFAULT 0,
    `resident_tax` BIGINT DEFAULT 0,
    `national_pension` INT DEFAULT 0,
    `health_insurance` INT DEFAULT 0,
    `employment_insurance` INT DEFAULT 0,
    `total_deduction` INT NOT NULL,
    `net_pay` INT NOT NULL,
    `pay_date` VARCHAR(20),
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `status` VARCHAR(50) DEFAULT 'confirmed',
    `long_care` INT DEFAULT 0,
    `employer_pension` INT DEFAULT 0,
    `employer_health` INT DEFAULT 0,
    `employer_employment` INT DEFAULT 0,
    `employer_accident` BIGINT DEFAULT 0,
    `premium_rule` VARCHAR(255) DEFAULT '',
    `transfer_file_at` VARCHAR(255),
    `paid_at` VARCHAR(255),
    `pay_doc_id` BIGINT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `po_lines`;
CREATE TABLE `po_lines` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `po_id` BIGINT NOT NULL,
    `line_no` INT,
    `item_id` BIGINT NOT NULL,
    `quantity` INT NOT NULL,
    `unit_price` INT NOT NULL,
    `amount` INT NOT NULL,
    `received_qty` INT DEFAULT 0,
    `returned_qty` DECIMAL(15, 2) NOT NULL DEFAULT 0,
    `account_code` VARCHAR(50) NOT NULL DEFAULT '',
    `dept` VARCHAR(50) NOT NULL DEFAULT '',
    `project_code` VARCHAR(255) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `post_likes`;
CREATE TABLE `post_likes` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `post_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `posts`;
CREATE TABLE `posts` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL,
    `category` VARCHAR(255) NOT NULL DEFAULT 'general',
    `title` VARCHAR(255) NOT NULL DEFAULT '',
    `content` TEXT NOT NULL,
    `author` VARCHAR(255) NOT NULL DEFAULT '',
    `dept` VARCHAR(50) NOT NULL DEFAULT '',
    `views` INT NOT NULL DEFAULT 0,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `pr_lines`;
CREATE TABLE `pr_lines` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `pr_id` BIGINT NOT NULL,
    `line_no` INT NOT NULL,
    `item_id` BIGINT,
    `item_name` VARCHAR(255) NOT NULL,
    `quantity` INT NOT NULL DEFAULT 1,
    `estimated_price` INT DEFAULT 0,
    `notes` TEXT,
    `account_code` VARCHAR(50) NOT NULL DEFAULT '',
    `dept` VARCHAR(50) NOT NULL DEFAULT '',
    `project_code` VARCHAR(255) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `price_groups`;
CREATE TABLE `price_groups` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `rate` DECIMAL(15, 2) NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `production_results`;
CREATE TABLE `production_results` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `wo_id` BIGINT NOT NULL,
    `result_date` VARCHAR(20) NOT NULL,
    `good_qty` INT NOT NULL,
    `defect_qty` INT DEFAULT 0,
    `worker_id` BIGINT,
    `notes` TEXT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `created_by` INT,
    `task_id` BIGINT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `purchase_orders`;
CREATE TABLE `purchase_orders` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `po_number` VARCHAR(255) NOT NULL,
    `partner_id` BIGINT,
    `po_date` VARCHAR(20) NOT NULL,
    `delivery_date` VARCHAR(20),
    `status` VARCHAR(50) DEFAULT 'draft',
    `doc_id` BIGINT,
    `total_amount` INT DEFAULT 0,
    `tax_amount` INT DEFAULT 0,
    `notes` TEXT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME,
    `task_id` BIGINT,
    `company_id` BIGINT,
    `contact_id` BIGINT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `purchase_requisitions`;
CREATE TABLE `purchase_requisitions` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `pr_number` VARCHAR(255) NOT NULL,
    `requester_id` BIGINT NOT NULL,
    `dept` VARCHAR(50),
    `request_date` VARCHAR(20) NOT NULL,
    `need_date` VARCHAR(20),
    `status` VARCHAR(50) NOT NULL DEFAULT 'draft',
    `notes` TEXT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `task_id` BIGINT,
    `company_id` BIGINT,
    `approved_by` INT,
    `approved_at` VARCHAR(255),
    `reject_reason` TEXT,
    `doc_id` BIGINT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `quotations`;
CREATE TABLE `quotations` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `quote_number` VARCHAR(255) NOT NULL,
    `partner_id` BIGINT,
    `quote_date` VARCHAR(20) NOT NULL,
    `valid_until` VARCHAR(255),
    `status` VARCHAR(50) DEFAULT 'draft',
    `total_amount` INT DEFAULT 0,
    `tax_amount` INT DEFAULT 0,
    `notes` TEXT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `task_id` BIGINT,
    `company_id` BIGINT,
    `contact_id` BIGINT,
    `ship_to` VARCHAR(255) DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `quote_lines`;
CREATE TABLE `quote_lines` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `quote_id` BIGINT NOT NULL,
    `line_no` INT,
    `item_id` BIGINT NOT NULL,
    `quantity` INT NOT NULL,
    `unit_price` INT NOT NULL,
    `discount_rate` DECIMAL(15, 2) DEFAULT 0,
    `amount` INT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `re_appropriations`;
CREATE TABLE `re_appropriations` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `year` INT NOT NULL,
    `approve_date` VARCHAR(20) NOT NULL,
    `legal_reserve` INT NOT NULL DEFAULT 0,
    `cash_div` INT NOT NULL DEFAULT 0,
    `other_reserve` INT NOT NULL DEFAULT 0,
    `doc_id` BIGINT,
    `created_by` INT,
    `created_at` DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `recurring_posts`;
CREATE TABLE `recurring_posts` (
    `recurring_id` BIGINT NOT NULL,
    `ym` VARCHAR(255) NOT NULL,
    `doc_id` BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `recurring_slips`;
CREATE TABLE `recurring_slips` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `title` VARCHAR(255) NOT NULL,
    `day` INT NOT NULL DEFAULT 0,
    `lines_json` TEXT NOT NULL,
    `start_ym` VARCHAR(255) NOT NULL,
    `end_ym` VARCHAR(255) NOT NULL,
    `status` VARCHAR(50) NOT NULL DEFAULT 'active',
    `created_by` INT,
    `created_at` DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `rfq_lines`;
CREATE TABLE `rfq_lines` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `rfq_id` BIGINT NOT NULL,
    `line_no` INT NOT NULL,
    `item_id` BIGINT NOT NULL,
    `quantity` INT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `rfq_quotes`;
CREATE TABLE `rfq_quotes` (
    `vendor_id` BIGINT NOT NULL,
    `line_id` BIGINT NOT NULL,
    `price` INT NOT NULL,
    PRIMARY KEY (`vendor_id`, `line_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `rfq_vendors`;
CREATE TABLE `rfq_vendors` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `rfq_id` BIGINT NOT NULL,
    `partner_id` BIGINT NOT NULL,
    `quote_date` VARCHAR(20) DEFAULT '',
    `valid_to` VARCHAR(255) DEFAULT '',
    `lead_days` INT NOT NULL DEFAULT 0,
    `notes` TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `rfqs`;
CREATE TABLE `rfqs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `rfq_number` VARCHAR(255) NOT NULL,
    `pr_id` BIGINT,
    `rfq_date` VARCHAR(20) NOT NULL,
    `due_date` VARCHAR(20) DEFAULT '',
    `status` VARCHAR(50) NOT NULL DEFAULT 'open',
    `partner_id` BIGINT,
    `doc_id` BIGINT,
    `po_id` BIGINT,
    `notes` TEXT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `sales_orders`;
CREATE TABLE `sales_orders` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `so_number` VARCHAR(255) NOT NULL,
    `quote_id` BIGINT,
    `partner_id` BIGINT,
    `order_date` VARCHAR(20) NOT NULL,
    `delivery_date` VARCHAR(20),
    `status` VARCHAR(50) DEFAULT 'confirmed',
    `total_amount` INT DEFAULT 0,
    `tax_amount` INT DEFAULT 0,
    `notes` TEXT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `task_id` BIGINT,
    `company_id` BIGINT,
    `contact_id` BIGINT,
    `ship_to` VARCHAR(255) DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `schema_versions`;
CREATE TABLE `schema_versions` (
    `version` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `applied_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `settlement_items`;
CREATE TABLE `settlement_items` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `settlement_id` BIGINT NOT NULL,
    `charge_doc_id` BIGINT NOT NULL,
    `amount` INT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `settlements`;
CREATE TABLE `settlements` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `kind` VARCHAR(255) NOT NULL,
    `settle_date` VARCHAR(20) NOT NULL,
    `partner_id` BIGINT NOT NULL,
    `amount` INT NOT NULL,
    `method` VARCHAR(255) NOT NULL,
    `bank_account_id` BIGINT,
    `account_code` VARCHAR(50) NOT NULL,
    `wht_type` VARCHAR(255) NOT NULL DEFAULT '없음',
    `wht_amt` INT NOT NULL DEFAULT 0,
    `doc_id` BIGINT,
    `memo` TEXT NOT NULL,
    `created_by` INT,
    `created_at` DATETIME NOT NULL,
    `canceled_at` VARCHAR(255),
    `cancel_doc_id` BIGINT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `severance_records`;
CREATE TABLE `severance_records` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `employee_id` BIGINT,
    `calc_date` VARCHAR(20),
    `avg_salary` INT,
    `tenure_days` INT,
    `amount` INT,
    `status` VARCHAR(50) DEFAULT 'pending',
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `income_tax` INT DEFAULT 0,
    `local_tax` INT DEFAULT 0,
    `net_amount` INT DEFAULT 0,
    `leave_days` DECIMAL(15, 2) DEFAULT 0,
    `leave_pay` INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `ship_lines`;
CREATE TABLE `ship_lines` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `ship_id` BIGINT NOT NULL,
    `so_line_id` BIGINT,
    `item_id` BIGINT NOT NULL,
    `shipped_qty` INT NOT NULL,
    `orig_line_id` BIGINT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `shipments`;
CREATE TABLE `shipments` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `ship_number` VARCHAR(255) NOT NULL,
    `so_id` BIGINT,
    `warehouse_id` BIGINT,
    `ship_date` VARCHAR(20) NOT NULL,
    `status` VARCHAR(50) DEFAULT 'draft',
    `notes` TEXT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `task_id` BIGINT,
    `company_id` BIGINT,
    `contact_id` BIGINT,
    `ship_to` VARCHAR(255) DEFAULT '',
    `kind` VARCHAR(255) NOT NULL DEFAULT '출고',
    `canceled_at` VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `slip_lines`;
CREATE TABLE `slip_lines` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `doc_id` BIGINT NOT NULL,
    `line_no` INT NOT NULL,
    `account_name` VARCHAR(255) NOT NULL,
    `account_code` VARCHAR(50) DEFAULT '',
    `debit` INT DEFAULT 0,
    `credit` INT DEFAULT 0,
    `partner` VARCHAR(255) DEFAULT '',
    `summary` VARCHAR(255) DEFAULT '',
    `partner_id` BIGINT,
    `dept` VARCHAR(50) DEFAULT '',
    `project_code` VARCHAR(255) DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `slip_seqs`;
CREATE TABLE `slip_seqs` (
    `company_id` BIGINT NOT NULL,
    `slip_date` VARCHAR(20) NOT NULL,
    `last_no` INT NOT NULL DEFAULT 0,
    PRIMARY KEY (`company_id`, `slip_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `so_lines`;
CREATE TABLE `so_lines` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `so_id` BIGINT NOT NULL,
    `line_no` INT,
    `item_id` BIGINT NOT NULL,
    `quantity` INT NOT NULL,
    `unit_price` INT NOT NULL,
    `amount` INT NOT NULL,
    `shipped_qty` INT DEFAULT 0,
    `returned_qty` DECIMAL(15, 2) NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `stock`;
CREATE TABLE `stock` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `item_id` BIGINT NOT NULL,
    `warehouse_id` BIGINT NOT NULL,
    `quantity` INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `stock_moves`;
CREATE TABLE `stock_moves` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `kind` VARCHAR(255) NOT NULL,
    `move_number` VARCHAR(255) NOT NULL,
    `move_date` VARCHAR(20) NOT NULL,
    `warehouse_id` BIGINT NOT NULL,
    `to_wh_id` BIGINT,
    `reason` TEXT,
    `notes` TEXT,
    `doc_id` BIGINT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `stock_transactions`;
CREATE TABLE `stock_transactions` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `item_id` BIGINT NOT NULL,
    `warehouse_id` BIGINT NOT NULL,
    `trans_date` VARCHAR(20) NOT NULL,
    `trans_type` VARCHAR(255) NOT NULL,
    `quantity` INT NOT NULL,
    `ref_type` VARCHAR(255),
    `ref_id` BIGINT,
    `balance_qty` INT,
    `notes` TEXT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `amount` INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `subsidy_offsets`;
CREATE TABLE `subsidy_offsets` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `employee_id` BIGINT NOT NULL,
    `pay_year` INT NOT NULL,
    `pay_month` INT NOT NULL,
    `amount` INT NOT NULL DEFAULT 0,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `subsidy_rates`;
CREATE TABLE `subsidy_rates` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `rate_key` VARCHAR(255) NOT NULL,
    `amount` INT NOT NULL,
    `effective_date` VARCHAR(20) NOT NULL,
    `reason` TEXT,
    `created_by` INT,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `task_comments`;
CREATE TABLE `task_comments` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `task_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL,
    `author` VARCHAR(255) NOT NULL DEFAULT '',
    `content` TEXT NOT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `task_deliverables`;
CREATE TABLE `task_deliverables` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `task_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL,
    `file_name` VARCHAR(255) DEFAULT '',
    `file_path` VARCHAR(255) DEFAULT '',
    `comment` VARCHAR(255) DEFAULT '',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `tasks`;
CREATE TABLE `tasks` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `work_request_id` BIGINT,
    `title` VARCHAR(255) NOT NULL,
    `description` TEXT,
    `task_type` VARCHAR(255) NOT NULL,
    `assigned_to` INT,
    `assigned_by` INT,
    `status` VARCHAR(50) DEFAULT 'pending',
    `priority` VARCHAR(255) DEFAULT 'normal',
    `due_date` VARCHAR(20),
    `started_at` VARCHAR(255),
    `completed_at` VARCHAR(255),
    `review_notes` TEXT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `requested_volume` INT DEFAULT 0,
    `completed_volume` INT DEFAULT 0,
    `sort_order` INT DEFAULT 0,
    `erp_module` VARCHAR(255) DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `tax_invoice_items`;
CREATE TABLE `tax_invoice_items` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `invoice_id` BIGINT NOT NULL,
    `line_no` INT NOT NULL,
    `item_date` VARCHAR(20),
    `name` VARCHAR(100) NOT NULL,
    `spec` VARCHAR(255) DEFAULT '',
    `qty` INT DEFAULT 0,
    `unit_price` INT DEFAULT 0,
    `supply_amt` INT NOT NULL,
    `vat` INT NOT NULL DEFAULT 0,
    `note` TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `tax_invoices`;
CREATE TABLE `tax_invoices` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL DEFAULT 0,
    `kind` VARCHAR(255) NOT NULL,
    `tax_type` VARCHAR(255) NOT NULL DEFAULT '과세',
    `evidence` VARCHAR(255) NOT NULL DEFAULT '세금계산서',
    `issue_date` VARCHAR(20) NOT NULL,
    `partner_id` BIGINT,
    `supply_amt` INT NOT NULL,
    `vat` INT NOT NULL DEFAULT 0,
    `total` INT NOT NULL,
    `approval_no` VARCHAR(255) DEFAULT '',
    `is_electronic` TINYINT(1) DEFAULT 1,
    `deduct` INT DEFAULT 1,
    `doc_id` BIGINT,
    `source_type` VARCHAR(255) DEFAULT 'manual',
    `source_id` BIGINT,
    `status` VARCHAR(50) NOT NULL DEFAULT '정상',
    `orig_id` BIGINT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `receipt_type` VARCHAR(255) DEFAULT '청구',
    `remark` VARCHAR(255) DEFAULT '',
    `amend_reason` INT,
    `contact_id` BIGINT,
    `lc_no` VARCHAR(255) DEFAULT '',
    `lc_open_date` VARCHAR(20),
    `nondeduct_reason` INT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `trans_requests`;
CREATE TABLE `trans_requests` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL,
    `translator_name` VARCHAR(255) NOT NULL,
    `service_type` VARCHAR(255) DEFAULT '',
    `request_date` VARCHAR(20) DEFAULT '',
    `request_time` VARCHAR(255) DEFAULT '',
    `duration` VARCHAR(255) DEFAULT '',
    `meeting_link` VARCHAR(255) DEFAULT '',
    `details` VARCHAR(255) DEFAULT '',
    `status` VARCHAR(50) DEFAULT 'pending',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `txn_rules`;
CREATE TABLE `txn_rules` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `keyword` VARCHAR(255) NOT NULL,
    `account_code` VARCHAR(50) NOT NULL,
    `partner_id` BIGINT,
    `hit_cnt` INT NOT NULL DEFAULT 0,
    `created_by` INT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `user_perms`;
CREATE TABLE `user_perms` (
    `user_id` BIGINT NOT NULL,
    `group_key` VARCHAR(255) NOT NULL,
    `level` VARCHAR(255) NOT NULL,
    PRIMARY KEY (`user_id`, `group_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `users`;
CREATE TABLE `users` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(100) NOT NULL,
    `password` VARCHAR(255) NOT NULL,
    `name` VARCHAR(100) NOT NULL DEFAULT '',
    `dept` VARCHAR(50) NOT NULL DEFAULT '경영지원팀',
    `role` VARCHAR(50) NOT NULL DEFAULT 'employee',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `position` VARCHAR(255) DEFAULT '',
    `phone` VARCHAR(100) DEFAULT '',
    `accessibility_settings` TEXT,
    `is_hr_admin` TINYINT(1) DEFAULT 0,
    `locked_until` DATETIME,
    `must_change_password` TINYINT(1) NOT NULL DEFAULT 0,
    `sess_ver` INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `warehouses`;
CREATE TABLE `warehouses` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL DEFAULT 0,
    `code` VARCHAR(50) NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `location` VARCHAR(255) DEFAULT '',
    `is_active` TINYINT(1) DEFAULT 1,
    `created_by` INT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `work_items`;
CREATE TABLE `work_items` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `request_id` BIGINT NOT NULL,
    `task_id` BIGINT,
    `seq` INT NOT NULL,
    `source` VARCHAR(255) DEFAULT '',
    `result` VARCHAR(255) DEFAULT '',
    `status` VARCHAR(50) NOT NULL DEFAULT 'open',
    `hold_note` TEXT,
    `done_by` INT,
    `done_at` VARCHAR(255),
    `sampled` TINYINT(1) DEFAULT 0,
    `round` INT DEFAULT 0,
    `reviewed_by` INT,
    `reviewed_at` VARCHAR(255),
    `review_note` TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `work_orders`;
CREATE TABLE `work_orders` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `wo_number` VARCHAR(255) NOT NULL,
    `product_id` BIGINT NOT NULL,
    `bom_id` BIGINT,
    `planned_qty` INT NOT NULL,
    `actual_qty` INT DEFAULT 0,
    `planned_start` VARCHAR(255),
    `planned_end` VARCHAR(255),
    `actual_start` VARCHAR(255),
    `actual_end` VARCHAR(255),
    `worker_id` BIGINT,
    `status` VARCHAR(50) DEFAULT 'planned',
    `doc_id` BIGINT,
    `notes` TEXT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `task_id` BIGINT,
    `company_id` BIGINT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `work_request_attachments`;
CREATE TABLE `work_request_attachments` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `request_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL,
    `file_name` VARCHAR(255) DEFAULT '',
    `file_path` VARCHAR(255) DEFAULT '',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `work_request_comments`;
CREATE TABLE `work_request_comments` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `request_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL,
    `author` VARCHAR(255) NOT NULL DEFAULT '',
    `content` TEXT NOT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `is_internal` TINYINT(1) DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `work_requests`;
CREATE TABLE `work_requests` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `requested_by` INT,
    `title` VARCHAR(255) NOT NULL,
    `description` TEXT,
    `task_type` VARCHAR(255) NOT NULL,
    `volume` INT DEFAULT 1,
    `priority` VARCHAR(255) DEFAULT 'normal',
    `status` VARCHAR(50) DEFAULT 'pending',
    `due_date` VARCHAR(20),
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `assigned_to` INT,
    `assigned_by` INT,
    `output_format` VARCHAR(255) DEFAULT 'excel',
    `submitted_at` VARCHAR(255),
    `accepted_at` VARCHAR(255),
    `completed_at` VARCHAR(255),
    `closed_at` VARCHAR(255),
    `reject_reason` TEXT,
    `total_volume` INT DEFAULT 0,
    `completed_volume` INT DEFAULT 0,
    `rejected_at` VARCHAR(255),
    `item_spec` VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `work_schedules`;
CREATE TABLE `work_schedules` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `company_id` BIGINT NOT NULL,
    `start_time` VARCHAR(255) NOT NULL DEFAULT '09:00',
    `end_time` VARCHAR(255) NOT NULL DEFAULT '18:00',
    `break_min` INT NOT NULL DEFAULT 60,
    `rest_day` INT NOT NULL DEFAULT 6,
    `off_day` INT NOT NULL DEFAULT 5
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `worker_evaluations`;
CREATE TABLE `worker_evaluations` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `employee_id` BIGINT NOT NULL,
    `company_id` BIGINT NOT NULL,
    `eval_year` INT NOT NULL,
    `eval_quarter` INT NOT NULL,
    `work_quality` INT DEFAULT 3,
    `work_attitude` INT DEFAULT 3,
    `cooperation` INT DEFAULT 3,
    `punctuality` INT DEFAULT 3,
    `overall_score` DECIMAL(15, 2),
    `strengths` VARCHAR(255),
    `improvements` VARCHAR(255),
    `comments` VARCHAR(255),
    `evaluator_id` BIGINT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Indexes
-- ----------------------------------------------------------------------------

CREATE INDEX `idx_employees_company` ON `employees` (`company_id`);
CREATE INDEX `idx_leave_requests_employee` ON `leave_requests` (`employee_id`);
CREATE INDEX `idx_attendance_logs_att` ON `attendance_logs` (`attendance_id`);
CREATE INDEX `idx_insurance_rates_key_date` ON `insurance_rates` (`rate_key`, `effective_date`);
CREATE INDEX `idx_activity_target` ON `activity_logs` (`target_type`, `target_id`);
CREATE INDEX `idx_notif_user` ON `notifications` (`user_id`, `is_read`);
CREATE INDEX `idx_closing_logs_closing` ON `attendance_closing_logs` (`closing_id`);
CREATE INDEX `idx_erp_activity_user_date` ON `erp_activity_log` (`user_id`, `created_at`);
CREATE INDEX `idx_export_logs_company` ON `export_logs` (`company_id`, `created_at`);
CREATE UNIQUE INDEX `idx_attendance_emp_date` ON `attendance` (`employee_id`, `work_date`);
CREATE INDEX `idx_leave_accruals_emp` ON `leave_accruals` (`employee_id`);
CREATE INDEX `idx_docs_book` ON `erp_docs` (`company_id`, `slip_date`);
CREATE INDEX `idx_bank_accounts_book` ON `bank_accounts` (`company_id`, `is_active`);
CREATE INDEX `idx_purchase_orders_company` ON `purchase_orders` (`company_id`);
CREATE INDEX `idx_quotations_company` ON `quotations` (`company_id`);
CREATE INDEX `idx_sales_orders_company` ON `sales_orders` (`company_id`);
CREATE INDEX `idx_goods_receipts_company` ON `goods_receipts` (`company_id`);
CREATE INDEX `idx_shipments_company` ON `shipments` (`company_id`);
CREATE INDEX `idx_bom_headers_company` ON `bom_headers` (`company_id`);
CREATE INDEX `idx_work_orders_company` ON `work_orders` (`company_id`);
CREATE INDEX `idx_purchase_requisitions_company` ON `purchase_requisitions` (`company_id`);
CREATE INDEX `idx_items_company` ON `items` (`company_id`);
CREATE INDEX `idx_warehouses_company` ON `warehouses` (`company_id`);
CREATE INDEX `idx_payslip_items_payslip` ON `payslip_items` (`payslip_id`);
CREATE INDEX `idx_payslips_period` ON `payslips` (`pay_year`, `pay_month`);
CREATE INDEX `idx_memo_codes_book` ON `memo_codes` (`company_id`, `is_active`);
CREATE INDEX `idx_approval_lines_user` ON `approval_lines` (`approver_id`, `status`);
CREATE INDEX `idx_approval_lines_doc` ON `approval_lines` (`doc_id`, `step`);
CREATE INDEX `idx_tax_inv_book` ON `tax_invoices` (`company_id`, `issue_date`);
CREATE INDEX `idx_tax_inv_doc` ON `tax_invoices` (`doc_id`);
CREATE INDEX `idx_tax_inv_orig` ON `tax_invoices` (`orig_id`);
CREATE INDEX `idx_stock_moves_company` ON `stock_moves` (`company_id`, `kind`, `move_date`);
CREATE INDEX `idx_partner_contacts` ON `partner_contacts` (`partner_id`, `sort`);
CREATE INDEX `idx_crm_leads` ON `crm_leads` (`company_id`, `status`);
CREATE INDEX `idx_crm_opps` ON `crm_opps` (`company_id`, `stage`);
CREATE INDEX `idx_crm_acts` ON `crm_activities` (`company_id`, `act_date`);
CREATE INDEX `idx_crm_acts_partner` ON `crm_activities` (`partner_id`);
CREATE INDEX `idx_partner_addrs` ON `partner_addrs` (`partner_id`, `sort`);
CREATE INDEX `idx_partner_banks` ON `partner_banks` (`partner_id`, `sort`);
CREATE INDEX `idx_partner_files` ON `partner_files` (`partner_id`);
CREATE INDEX `idx_partner_history` ON `partner_history` (`partner_id`, `id`);
CREATE INDEX `idx_crm_acts_contact` ON `crm_activities` (`contact_id`);
CREATE INDEX `idx_audit_company_at` ON `audit_logs` (`company_id`, `at`);
CREATE INDEX `idx_audit_target` ON `audit_logs` (`target_type`, `target_id`);
CREATE INDEX `idx_login_attempts_user_at` ON `login_attempts` (`username`, `at`);
CREATE INDEX `idx_settlements_company` ON `settlements` (`company_id`, `settle_date`);
CREATE INDEX `idx_settlements_partner` ON `settlements` (`partner_id`);
CREATE INDEX `idx_settlement_items_charge` ON `settlement_items` (`charge_doc_id`);
CREATE INDEX `idx_settlement_items_settle` ON `settlement_items` (`settlement_id`);
CREATE INDEX `idx_bank_txns_account` ON `bank_txns` (`company_id`, `bank_account_id`, `txn_at`);
CREATE UNIQUE INDEX `idx_tax_invoices_approval` ON `tax_invoices` (`company_id`, `approval_no`);
CREATE INDEX `idx_gr_lines_orig` ON `gr_lines` (`orig_line_id`);
CREATE INDEX `idx_ship_lines_orig` ON `ship_lines` (`orig_line_id`);
CREATE INDEX `idx_rfqs_company` ON `rfqs` (`company_id`, `status`);
CREATE INDEX `idx_depts_book` ON `depts` (`company_id`, `is_active`);
CREATE INDEX `idx_employee_files_emp` ON `employee_files` (`employee_id`);
CREATE INDEX `idx_employee_files_company` ON `employee_files` (`company_id`);
CREATE INDEX `idx_hr_appointments_emp` ON `hr_appointments` (`employee_id`, `id`);
CREATE INDEX `idx_hr_appointments_company` ON `hr_appointments` (`company_id`);
CREATE INDEX `idx_fa_capex_asset` ON `fa_capex` (`asset_id`);
CREATE INDEX `idx_approval_deputies_user` ON `approval_deputies` (`company_id`, `user_id`, `start_date`, `end_date`);
CREATE INDEX `idx_training_company` ON `disability_awareness_trainings` (`company_id`, `held_date`);
CREATE INDEX `idx_attendee_emp` ON `disability_awareness_attendees` (`employee_id`, `completed`);
CREATE INDEX `idx_budgets_dept` ON `budgets` (`company_id`, `dept`, `year`);
CREATE INDEX `idx_work_items_task_status` ON `work_items` (`task_id`, `status`);
CREATE INDEX `idx_labor_contracts_employee` ON `labor_contracts` (`employee_id`, `id`);
CREATE INDEX `idx_labor_contracts_company` ON `labor_contracts` (`company_id`);
CREATE INDEX `idx_subsidy_rates_key_date` ON `subsidy_rates` (`rate_key`, `effective_date`);
CREATE INDEX `idx_notes_book` ON `notes` (`company_id`);
CREATE INDEX `idx_accruals_company` ON `accruals` (`company_id`, `status`);
CREATE INDEX `idx_recurring_company` ON `recurring_slips` (`company_id`, `status`);
CREATE INDEX `idx_re_approp_book` ON `re_appropriations` (`company_id`, `year`);
CREATE INDEX `idx_card_txns_book` ON `card_txns` (`company_id`);
CREATE INDEX `idx_budget_changes_book` ON `budget_changes` (`company_id`, `dept`, `account_code`, `year`, `month`);

SET FOREIGN_KEY_CHECKS = 1;
-- 学习助手当前数据库 DDL（现状兼容版）
-- 更新日期：2026-04-16
-- 历史参考说明：
-- 这份 SQL 来自早期 MySQL 设计包，只作为历史/迁移参考保留。
-- 当前正式运行时已经收口为 PostgreSQL + PGVector，请勿把本文件当作当前部署 DDL。
-- 说明：
-- 1. 这份 SQL 以当前项目 SQLAlchemy ORM 为准
-- 2. 目标是帮助理解和部署，不是强约束迁移脚本
-- 3. 产品语义是 notebook，但当前数据库内部仍保留 subject 命名
-- 4. 当前实现主用 MySQL，开发环境可回退 SQLite
-- 5. 当前未显式声明 FOREIGN KEY，关系主要由应用层维护

CREATE TABLE IF NOT EXISTS `subjects` (
  `id` VARCHAR(64) NOT NULL,
  `name` VARCHAR(100) NOT NULL,
  `icon` VARCHAR(16) NOT NULL DEFAULT '📚',
  `description` TEXT NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_subjects_name` (`name`),
  KEY `ix_subjects_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS `user_memories` (
  `user_id` VARCHAR(100) NOT NULL,
  `weak_points` JSON NOT NULL,
  `error_count` JSON NOT NULL,
  `recent_topics` JSON NOT NULL,
  `last_session` VARCHAR(200) NOT NULL DEFAULT '',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS `user_profiles` (
  `user_id` VARCHAR(100) NOT NULL,
  `display_name` VARCHAR(120) NOT NULL DEFAULT '',
  `agent_style_name` VARCHAR(120) NOT NULL DEFAULT '',
  `agent_style_prompt` TEXT NOT NULL,
  `onboarding_completed` BOOLEAN NOT NULL DEFAULT FALSE,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS `chat_sessions` (
  `id` VARCHAR(100) NOT NULL,
  `user_id` VARCHAR(100) NOT NULL,
  `subject_id` VARCHAR(64) NOT NULL DEFAULT 'general',
  `title` VARCHAR(120) NOT NULL DEFAULT '新对话',
  `messages` JSON NOT NULL,
  `latest_quiz` JSON NOT NULL,
  `session_memory` JSON NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_chat_sessions_user_id` (`user_id`),
  KEY `ix_chat_sessions_subject_id` (`subject_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS `question_bank_items` (
  `id` VARCHAR(100) NOT NULL,
  `subject_id` VARCHAR(64) NOT NULL DEFAULT 'general',
  `knowledge_point` VARCHAR(120) NOT NULL DEFAULT '',
  `stem` TEXT NOT NULL,
  `options_json` JSON NOT NULL,
  `correct_option` VARCHAR(1) NOT NULL DEFAULT 'A',
  `explanation` TEXT NOT NULL,
  `option_rationales_json` JSON NOT NULL,
  `source_name` VARCHAR(200) NOT NULL DEFAULT '',
  `source_year` INT NULL,
  `difficulty` VARCHAR(20) NOT NULL DEFAULT '基础',
  `tags_json` JSON NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_question_bank_items_subject_id` (`subject_id`),
  KEY `ix_question_bank_items_knowledge_point` (`knowledge_point`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS `practice_attempts` (
  `id` VARCHAR(100) NOT NULL,
  `user_id` VARCHAR(100) NOT NULL,
  `session_id` VARCHAR(100) NOT NULL DEFAULT '',
  `subject_id` VARCHAR(64) NOT NULL DEFAULT 'general',
  `question_id` VARCHAR(100) NOT NULL DEFAULT '',
  `question_snapshot` JSON NOT NULL,
  `selected_option` VARCHAR(1) NOT NULL DEFAULT '',
  `is_correct` BOOLEAN NOT NULL DEFAULT FALSE,
  `knowledge_point` VARCHAR(120) NOT NULL DEFAULT '',
  `source_type` VARCHAR(20) NOT NULL DEFAULT 'ai_generated',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_practice_attempts_user_id` (`user_id`),
  KEY `ix_practice_attempts_session_id` (`session_id`),
  KEY `ix_practice_attempts_subject_id` (`subject_id`),
  KEY `ix_practice_attempts_knowledge_point` (`knowledge_point`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS `app_settings` (
  `key` VARCHAR(100) NOT NULL,
  `value` TEXT NOT NULL,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- 推荐优化（未落地，仅作为后续迁移参考）
-- 1. 为 practice_attempts 增加组合索引：
--    KEY `ix_practice_attempts_user_point_time` (`user_id`, `knowledge_point`, `created_at`)
-- 2. 为 question_bank_items 增加组合索引：
--    KEY `ix_question_bank_items_lookup` (`subject_id`, `knowledge_point`, `difficulty`, `source_year`)
-- 3. 后续如需更强一致性，可补充以下外键：
--    chat_sessions.subject_id -> subjects.id
--    question_bank_items.subject_id -> subjects.id
--    practice_attempts.subject_id -> subjects.id
--    practice_attempts.question_id -> question_bank_items.id

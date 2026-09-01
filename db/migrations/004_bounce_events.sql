-- Bounce Detection: Tracks email bounce events for sender reputation protection
CREATE TABLE IF NOT EXISTS bounce_events (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    contact_id BIGINT UNSIGNED NULL,
    company_id BIGINT UNSIGNED NULL,
    email VARCHAR(255) NOT NULL,
    bounce_type ENUM('hard_bounce', 'soft_bounce', 'complaint', 'unknown') NOT NULL,
    dsn_code VARCHAR(20) NULL,
    raw_reason TEXT NULL,
    original_message_id BIGINT UNSIGNED NULL,
    suppressed TINYINT(1) DEFAULT 0,
    detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_email (email),
    INDEX idx_bounce_type (bounce_type),
    INDEX idx_detected (detected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

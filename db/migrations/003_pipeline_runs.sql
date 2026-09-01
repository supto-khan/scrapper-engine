-- Pipeline Health Monitor: Tracks execution metrics for each pipeline stage
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    stage_name VARCHAR(100) NOT NULL,
    status ENUM('running', 'success', 'failed', 'partial') NOT NULL DEFAULT 'running',
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP NULL,
    duration_seconds FLOAT NULL,
    items_processed INT UNSIGNED DEFAULT 0,
    items_failed INT UNSIGNED DEFAULT 0,
    error_message TEXT NULL,
    metrics JSON NULL,
    alerted TINYINT(1) DEFAULT 0,
    INDEX idx_stage_date (stage_name, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

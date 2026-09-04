# ==============================================================================
# Nexidant Signal Database Schema - Phase 1, 2, 3, 4 & 5
# Target Database: MySQL / MariaDB (Native VPS aaPanel setup)
# ==============================================================================

CREATE TABLE IF NOT EXISTS companies (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    domain VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    industry VARCHAR(100) NULL,
    employee_count_estimate VARCHAR(50) NULL,
    source VARCHAR(50) NOT NULL DEFAULT 'unknown',
    website_url VARCHAR(500) NULL,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_crawled_at TIMESTAMP NULL DEFAULT NULL,
    content_hash VARCHAR(64) NULL,
    report_pdf_path VARCHAR(500) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_companies_domain (domain),
    INDEX idx_companies_source (source),
    INDEX idx_companies_last_crawled (last_crawled_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS technologies (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    company_id BIGINT UNSIGNED NOT NULL,
    cms VARCHAR(100) NULL,
    frontend_stack JSON NULL,
    backend_stack JSON NULL,
    https BOOLEAN NOT NULL DEFAULT FALSE,
    hsts BOOLEAN NOT NULL DEFAULT FALSE,
    ttfb_ms INT UNSIGNED NULL,
    evidence JSON NULL,
    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    INDEX idx_tech_company_id (company_id),
    INDEX idx_tech_scanned_at (scanned_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS raw_company_data (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    company_id BIGINT UNSIGNED NOT NULL,
    source_url VARCHAR(1000) NOT NULL,
    http_status INT UNSIGNED NULL,
    headers JSON NULL,
    raw_html LONGTEXT NULL,
    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    INDEX idx_raw_company_id (company_id),
    INDEX idx_raw_crawled_at (crawled_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Phase 2 Tables: Audits, Signals, Opportunities

CREATE TABLE IF NOT EXISTS audits (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    company_id BIGINT UNSIGNED NOT NULL,
    url VARCHAR(1000) NOT NULL,
    performance_score INT UNSIGNED NULL,
    accessibility_score INT UNSIGNED NULL,
    seo_score INT UNSIGNED NULL,
    lcp_ms INT UNSIGNED NULL,
    cls FLOAT NULL,
    inp_ms INT UNSIGNED NULL,
    ttfb_ms INT UNSIGNED NULL,
    raw_audit_data JSON NULL,
    audited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    INDEX idx_audits_company_id (company_id),
    INDEX idx_audits_audited_at (audited_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS signals (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    company_id BIGINT UNSIGNED NOT NULL,
    type VARCHAR(50) NOT NULL,
    detail JSON NULL,
    confidence FLOAT NOT NULL DEFAULT 1.0,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    INDEX idx_signals_company_id (company_id),
    INDEX idx_signals_type (type),
    INDEX idx_signals_detected_at (detected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS opportunities (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    company_id BIGINT UNSIGNED NOT NULL,
    type VARCHAR(100) NOT NULL,
    evidence JSON NULL,
    estimated_value_low INT UNSIGNED NOT NULL DEFAULT 0,
    estimated_value_high INT UNSIGNED NOT NULL DEFAULT 0,
    confidence FLOAT NOT NULL DEFAULT 1.0,
    recommended_service VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'detected',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    INDEX idx_opportunities_company_id (company_id),
    INDEX idx_opportunities_type (type),
    INDEX idx_opportunities_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Phase 3 Table: Scores (Composite Weighted Opportunity Scoring)

CREATE TABLE IF NOT EXISTS scores (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    company_id BIGINT UNSIGNED NOT NULL,
    company_fit FLOAT NOT NULL DEFAULT 0.0,
    technology_gap FLOAT NOT NULL DEFAULT 0.0,
    pain_signal FLOAT NOT NULL DEFAULT 0.0,
    buying_signal FLOAT NOT NULL DEFAULT 0.0,
    contact_quality FLOAT NOT NULL DEFAULT 0.0,
    service_fit FLOAT NOT NULL DEFAULT 0.0,
    opportunity_score FLOAT NOT NULL DEFAULT 0.0,
    priority_tier VARCHAR(50) NOT NULL DEFAULT 'ignore',
    score_breakdown JSON NULL,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    INDEX idx_scores_company_id (company_id),
    INDEX idx_scores_opportunity_score (opportunity_score),
    INDEX idx_scores_priority_tier (priority_tier),
    INDEX idx_scores_computed_at (computed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Phase 4 Table: Contacts (Enriched Decision Makers & Validated Emails)

CREATE TABLE IF NOT EXISTS contacts (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    company_id BIGINT UNSIGNED NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    first_name VARCHAR(100) NULL,
    last_name VARCHAR(100) NULL,
    title VARCHAR(255) NULL,
    role_category VARCHAR(100) NULL,
    email VARCHAR(255) NOT NULL,
    email_status VARCHAR(50) NOT NULL DEFAULT 'unverified',
    email_score FLOAT NULL,
    verification_source VARCHAR(100) NULL,
    linkedin_url VARCHAR(500) NULL,
    source VARCHAR(50) NOT NULL DEFAULT 'hunter',
    raw_contact_data JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    INDEX idx_contacts_company_id (company_id),
    INDEX idx_contacts_email (email),
    INDEX idx_contacts_email_status (email_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Phase 5 Tables: Outreach Campaigns & Messages (Sales Automation)

CREATE TABLE IF NOT EXISTS outreach_campaigns (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    segment_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS outreach_messages (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    campaign_id BIGINT UNSIGNED NULL,
    company_id BIGINT UNSIGNED NOT NULL,
    contact_id BIGINT UNSIGNED NULL,
    recipient_email VARCHAR(255) NULL,
    channel VARCHAR(50) NOT NULL DEFAULT 'email',
    segment VARCHAR(100) NULL,
    subject VARCHAR(255) NOT NULL,
    body_text TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'queued',
    evidence_snapshot JSON NULL,
    error_message TEXT NULL,
    sent_at TIMESTAMP NULL,
    opened_at TIMESTAMP NULL,
    open_count INT UNSIGNED NOT NULL DEFAULT 0,
    clicked_at TIMESTAMP NULL,
    click_count INT UNSIGNED NOT NULL DEFAULT 0,
    staged_at TIMESTAMP NULL,
    scheduled_for TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL,
    FOREIGN KEY (campaign_id) REFERENCES outreach_campaigns(id) ON DELETE SET NULL,
    INDEX idx_outreach_company_id (company_id),
    INDEX idx_outreach_contact_id (contact_id),
    INDEX idx_outreach_status (status),
    INDEX idx_outreach_scheduled_for (scheduled_for)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Closed-Loop Calibration Engine: Track predicted dimension scores against real-world reply & conversion outcomes
CREATE TABLE IF NOT EXISTS outreach_outcomes (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    company_id BIGINT UNSIGNED NOT NULL,
    contact_id BIGINT UNSIGNED NOT NULL,
    message_id BIGINT UNSIGNED NULL,
    source VARCHAR(50) NOT NULL DEFAULT 'unknown',
    industry VARCHAR(100) NULL,
    initial_opportunity_score FLOAT NOT NULL,
    company_fit_score FLOAT NOT NULL,
    technology_gap_score FLOAT NOT NULL,
    pain_signal_score FLOAT NOT NULL,
    buying_signal_score FLOAT NOT NULL,
    contact_quality_score FLOAT NOT NULL,
    service_fit_score FLOAT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    opened BOOLEAN NOT NULL DEFAULT FALSE,
    replied BOOLEAN NOT NULL DEFAULT FALSE,
    meeting_booked BOOLEAN NOT NULL DEFAULT FALSE,
    closed_won BOOLEAN NOT NULL DEFAULT FALSE,
    deal_size_closed DECIMAL(10, 2) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES outreach_messages(id) ON DELETE SET NULL,
    INDEX idx_outcomes_company_id (company_id),
    INDEX idx_outcomes_source (source),
    INDEX idx_outcomes_replied (replied),
    INDEX idx_outcomes_closed_won (closed_won)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

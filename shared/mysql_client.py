import json
import os
import re
from typing import Any

try:
    import pymysql
    from pymysql.cursors import DictCursor
except ImportError:
    pymysql = None
    DictCursor = None

from dotenv import load_dotenv

from shared.redis_client import normalize_domain

load_dotenv()


class MySQLClient:
    """
    MySQL / MariaDB client for Signal Engine.
    Handles connection management, schema initialization, and upsert operations.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        db_name: str | None = None,
    ):
        self.host = host or os.getenv("DB_HOST", "127.0.0.1")
        self.port = int(port or os.getenv("DB_PORT", "3306"))
        self.user = user or os.getenv("DB_USER", "root")
        self.password = password or os.getenv("DB_PASSWORD", "")
        self.db_name = db_name or os.getenv("DB_NAME", "nexidant_signal")

    def get_connection(self, select_db: bool = True) -> pymysql.Connection:
        """Returns a new PyMySQL connection."""
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.db_name if select_db else None,
            cursorclass=DictCursor,
            autocommit=True,
            connect_timeout=5,
        )

    def ping(self) -> bool:
        """Checks database connectivity."""
        try:
            conn = self.get_connection(select_db=False)
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            conn.close()
            return True
        except Exception:
            return False

    def init_schema(self, schema_path: str = "db/schema.sql") -> bool:
        """Executes db/schema.sql to create necessary tables."""
        if not os.path.exists(schema_path):
            raise FileNotFoundError(f"Schema file not found at {schema_path}")

        with open(schema_path, encoding="utf-8") as f:
            sql_script = f.read()

        # Connect and ensure database exists
        conn = self.get_connection(select_db=False)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
                cursor.execute(f"USE `{self.db_name}`")

                # Split statements by semicolon
                statements = [
                    stmt.strip() for stmt in sql_script.split(";") if stmt.strip()
                ]
                for stmt in statements:
                    cursor.execute(stmt)
            return True
        finally:
            conn.close()

    def upsert_company(
        self,
        domain: str,
        name: str,
        source: str = "unknown",
        industry: str | None = None,
        employee_count_estimate: str | None = None,
        website_url: str | None = None,
    ) -> int:
        """
        Inserts or updates a company by normalized domain.
        Returns the company ID.
        """
        clean_domain = normalize_domain(domain)
        if not clean_domain:
            raise ValueError("Invalid domain provided")

        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                sql = """
                INSERT INTO companies (domain, name, source, industry, employee_count_estimate, website_url)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    name = IF(name = '' OR name IS NULL, VALUES(name), name),
                    industry = COALESCE(VALUES(industry), industry),
                    employee_count_estimate = COALESCE(VALUES(employee_count_estimate), employee_count_estimate),
                    website_url = COALESCE(VALUES(website_url), website_url),
                    updated_at = CURRENT_TIMESTAMP
                """
                cursor.execute(
                    sql,
                    (
                        clean_domain,
                        name,
                        source,
                        industry,
                        employee_count_estimate,
                        website_url,
                    ),
                )

                # Fetch company ID
                cursor.execute(
                    "SELECT id FROM companies WHERE domain = %s", (clean_domain,)
                )
                row = cursor.fetchone()
                return row["id"] if row else 0
        finally:
            conn.close()

    def update_company_domain(self, company_id: int, new_domain: str, website_url: str | None = None) -> bool:
        """
        Updates the domain and website_url for an existing company record (e.g. upgrading from .local to real domain).
        """
        clean_domain = normalize_domain(new_domain)
        clean_url = website_url or (f"https://{clean_domain}" if not clean_domain.endswith(".local") else None)
        try:
            conn = self.get_connection()
        except Exception:
            return False
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE companies 
                    SET domain = %s, website_url = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (clean_domain, clean_url, company_id),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to update company domain for ID {company_id}: {e}")
            return False
        finally:
            conn.close()

    def get_company_by_domain(self, domain: str) -> dict[str, Any] | None:
        """Fetches a company record by domain."""
        clean_domain = normalize_domain(domain)
        try:
            conn = self.get_connection()
        except Exception:
            return None
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM companies WHERE domain = %s", (clean_domain,)
                )
                return cursor.fetchone()
        except Exception:
            return None
        finally:
            conn.close()

    def get_company_by_name(self, name: str, city_slug: str | None = None) -> dict[str, Any] | None:
        """
        Fetches a company record by exact name, normalized name slug, or (name + city).
        Guarantees that identical business names across different queries/categories are not duplicated.
        """
        clean_name = (name or "").strip()
        if not clean_name:
            return None
        try:
            conn = self.get_connection()
        except Exception:
            return None
        try:
            with conn.cursor() as cursor:
                # 1. Exact case-insensitive name match
                cursor.execute(
                    "SELECT * FROM companies WHERE LOWER(TRIM(name)) = LOWER(%s) LIMIT 1",
                    (clean_name,)
                )
                row = cursor.fetchone()
                if row:
                    return row

                # 2. Local domain match with city slug if available
                if city_slug:
                    slug = re.sub(r"[^a-z0-9]+", "-", clean_name.lower()).strip("-")
                    if slug:
                        cursor.execute(
                            "SELECT * FROM companies WHERE domain LIKE %s LIMIT 1",
                            (f"{slug}-{city_slug}%",)
                        )
                        row = cursor.fetchone()
                        if row:
                            return row

                return None
        except Exception:
            return None
        finally:
            conn.close()

    def save_technology_fingerprint(
        self,
        company_id: int,
        cms: str | None = None,
        frontend_stack: list[str] | None = None,
        backend_stack: list[str] | None = None,
        https: bool = False,
        hsts: bool = False,
        ttfb_ms: int | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> int:
        """Records a scanned technology fingerprint for a company."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                sql = """
                INSERT INTO technologies (company_id, cms, frontend_stack, backend_stack, https, hsts, ttfb_ms, evidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(
                    sql,
                    (
                        company_id,
                        cms,
                        json.dumps(frontend_stack)
                        if frontend_stack is not None
                        else None,
                        json.dumps(backend_stack)
                        if backend_stack is not None
                        else None,
                        https,
                        hsts,
                        ttfb_ms,
                        json.dumps(evidence) if evidence is not None else None,
                    ),
                )
                return cursor.lastrowid
        finally:
            conn.close()

    def save_raw_company_data(
        self,
        company_id: int,
        source_url: str,
        http_status: int | None = None,
        headers: dict[str, Any] | None = None,
        raw_html: str | None = None,
    ) -> int:
        """Saves raw scraped snapshot for future re-scoring and provenance."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                sql = """
                INSERT INTO raw_company_data (company_id, source_url, http_status, headers, raw_html)
                VALUES (%s, %s, %s, %s, %s)
                """
                cursor.execute(
                    sql,
                    (
                        company_id,
                        source_url,
                        http_status,
                        json.dumps(headers) if headers is not None else None,
                        raw_html,
                    ),
                )
                return cursor.lastrowid
        finally:
            conn.close()

    # --- Phase 2 Methods ---

    def save_audit_result(
        self,
        company_id: int,
        url: str,
        performance_score: int | None = None,
        accessibility_score: int | None = None,
        seo_score: int | None = None,
        lcp_ms: int | None = None,
        cls: float | None = None,
        inp_ms: int | None = None,
        ttfb_ms: int | None = None,
        raw_audit_data: dict[str, Any] | None = None,
    ) -> int:
        """Saves website performance / Core Web Vitals audit result."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                sql = """
                INSERT INTO audits (company_id, url, performance_score, accessibility_score, seo_score, lcp_ms, cls, inp_ms, ttfb_ms, raw_audit_data)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(
                    sql,
                    (
                        company_id,
                        url,
                        performance_score,
                        accessibility_score,
                        seo_score,
                        lcp_ms,
                        cls,
                        inp_ms,
                        ttfb_ms,
                        json.dumps(raw_audit_data)
                        if raw_audit_data is not None
                        else None,
                    ),
                )
                return cursor.lastrowid
        finally:
            conn.close()

    def save_signal(
        self,
        company_id: int,
        type: str | None = None,
        detail: dict[str, Any] | None = None,
        confidence: float | None = None,
        *,
        signal_type: str | None = None,
        confidence_score: float | None = None,
        evidence_data: dict[str, Any] | None = None,
        source_url: str | None = None,
    ) -> int:
        """
        Saves a detected business or hiring signal.
        Supports both positional and keyword argument conventions.
        """
        final_type = signal_type or type or "generic_signal"
        final_confidence = confidence if confidence is not None else (confidence_score if confidence_score is not None else 1.0)
        
        final_detail = evidence_data if evidence_data is not None else (detail or {})
        if source_url and isinstance(final_detail, dict) and "source_url" not in final_detail:
            final_detail["source_url"] = source_url

        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                sql = """
                INSERT INTO signals (company_id, type, detail, confidence)
                VALUES (%s, %s, %s, %s)
                """
                cursor.execute(
                    sql,
                    (
                        company_id,
                        final_type,
                        json.dumps(final_detail) if final_detail is not None else None,
                        final_confidence,
                    ),
                )
                return cursor.lastrowid
        finally:
            conn.close()

    def save_opportunity(
        self,
        company_id: int,
        type: str | None = None,
        recommended_service: str | None = None,
        estimated_value_low: float = 0.0,
        estimated_value_high: float = 0.0,
        confidence: float = 1.0,
        evidence: dict[str, Any] | None = None,
        status: str = "detected",
        *,
        opportunity_type: str | None = None,
        title: str | None = None,
        pain_point: str | None = None,
        **kwargs: Any,
    ) -> int:
        """
        Saves a detected sales opportunity with service recommendation and estimated deal value.
        Updates existing opportunity for the same company_id and type to prevent duplicates.
        Supports both positional and keyword argument variations (opportunity_type, title, etc.).
        """
        final_type = opportunity_type or type or "general_opportunity"
        final_service = recommended_service or title or "Website & Conversion Optimization"
        final_evidence = dict(evidence or {})
        if pain_point and "pain_point" not in final_evidence:
            final_evidence["pain_point"] = pain_point

        final_confidence = confidence if confidence > 0.0 else float(kwargs.get("confidence_score", 1.0))

        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM opportunities WHERE company_id = %s AND type = %s LIMIT 1",
                    (company_id, final_type),
                )
                existing = cursor.fetchone()
                if existing:
                    opp_id = existing["id"]
                    sql_update = """
                    UPDATE opportunities 
                    SET recommended_service = %s,
                        estimated_value_low = %s,
                        estimated_value_high = %s,
                        confidence = %s,
                        evidence = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """
                    cursor.execute(
                        sql_update,
                        (
                            final_service,
                            estimated_value_low,
                            estimated_value_high,
                            final_confidence,
                            json.dumps(final_evidence) if final_evidence is not None else None,
                            opp_id,
                        ),
                    )
                    return opp_id

                sql = """
                INSERT INTO opportunities (company_id, type, recommended_service, estimated_value_low, estimated_value_high, confidence, evidence, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(
                    sql,
                    (
                        company_id,
                        final_type,
                        final_service,
                        estimated_value_low,
                        estimated_value_high,
                        final_confidence,
                        json.dumps(final_evidence) if final_evidence is not None else None,
                        status,
                    ),
                )
                return cursor.lastrowid
        finally:
            conn.close()

    # --- Phase 3 Methods ---

    def save_score(
        self,
        company_id: int,
        company_fit: float,
        technology_gap: float,
        pain_signal: float,
        buying_signal: float,
        contact_quality: float,
        service_fit: float,
        opportunity_score: float,
        priority_tier: str,
        score_breakdown: dict[str, Any] | None = None,
    ) -> int:
        """
        Saves computed lead score for a company.
        If the scores and priority tier have not changed since the previous scoring run,
        skips insertion to prevent redundant historical rows.
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                # 1. Fetch latest existing score record for this company
                cursor.execute(
                    """
                    SELECT id, company_fit, technology_gap, pain_signal, buying_signal,
                           contact_quality, service_fit, opportunity_score, priority_tier
                    FROM scores
                    WHERE company_id = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (company_id,),
                )
                existing = cursor.fetchone()

                # 2. Compare values to detect if anything actually changed
                if existing:
                    def _is_close(a: Any, b: Any, tol: float = 0.01) -> bool:
                        if a is None and b is None:
                            return True
                        if a is None or b is None:
                            return False
                        try:
                            return abs(float(a) - float(b)) < tol
                        except (ValueError, TypeError):
                            return a == b

                    scores_unchanged = (
                        _is_close(existing.get("company_fit"), company_fit)
                        and _is_close(existing.get("technology_gap"), technology_gap)
                        and _is_close(existing.get("pain_signal"), pain_signal)
                        and _is_close(existing.get("buying_signal"), buying_signal)
                        and _is_close(existing.get("contact_quality"), contact_quality)
                        and _is_close(existing.get("service_fit"), service_fit)
                        and _is_close(existing.get("opportunity_score"), opportunity_score)
                        and str(existing.get("priority_tier") or "").lower() == str(priority_tier or "").lower()
                    )

                    if scores_unchanged:
                        # Unchanged: Return existing score ID without adding a duplicate row
                        return existing["id"]

                # 3. Score has changed or is new: Insert new record
                sql = """
                INSERT INTO scores (company_id, company_fit, technology_gap, pain_signal, buying_signal, contact_quality, service_fit, opportunity_score, priority_tier, score_breakdown)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(
                    sql,
                    (
                        company_id,
                        company_fit,
                        technology_gap,
                        pain_signal,
                        buying_signal,
                        contact_quality,
                        service_fit,
                        opportunity_score,
                        priority_tier,
                        json.dumps(score_breakdown)
                        if score_breakdown is not None
                        else None,
                    ),
                )
                return cursor.lastrowid
        finally:
            conn.close()

    # --- Phase 4 Methods ---

    def save_contact(
        self,
        company_id: int,
        full_name: str,
        email: str,
        first_name: str | None = None,
        last_name: str | None = None,
        title: str | None = None,
        role_category: str | None = None,
        email_status: str = "unverified",
        email_score: float | None = None,
        verification_source: str | None = None,
        linkedin_url: str | None = None,
        source: str = "hunter",
        raw_contact_data: dict[str, Any] | None = None,
    ) -> int:
        """Saves an enriched decision-maker contact for a company."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                sql = """
                INSERT INTO contacts (
                    company_id, full_name, first_name, last_name, title,
                    role_category, email, email_status, email_score,
                    verification_source, linkedin_url, source, raw_contact_data
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(
                    sql,
                    (
                        company_id,
                        full_name,
                        first_name,
                        last_name,
                        title,
                        role_category,
                        email,
                        email_status,
                        email_score,
                        verification_source,
                        linkedin_url,
                        source,
                        json.dumps(raw_contact_data)
                        if raw_contact_data is not None
                        else None,
                    ),
                )
                return cursor.lastrowid
        finally:
            conn.close()

    def get_company_contacts(self, company_id: int) -> list[dict[str, Any]]:
        """Fetches all enriched contacts for a specific company."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM contacts WHERE company_id = %s ORDER BY id ASC",
                    (company_id,),
                )
                return cursor.fetchall()
        finally:
            conn.close()

    # --- Phase 5 Methods ---

    def save_outreach_campaign(self, name: str, segment_type: str) -> int:
        """Creates or gets an outreach campaign."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                sql = "INSERT INTO outreach_campaigns (name, segment_type) VALUES (%s, %s)"
                cursor.execute(sql, (name, segment_type))
                return cursor.lastrowid
        finally:
            conn.close()

    def has_existing_outreach(
        self,
        company_id: int | None = None,
        contact_id: int | None = None,
        email: str | None = None,
    ) -> bool:
        """
        Checks if an outbound outreach message (queued, staged, sent, delivered, etc.)
        already exists for the given company, contact, or email address.
        Prevents duplicate pitches to the same company/inbox.
        """
        try:
            conn = self.get_connection()
        except Exception:
            return False

        try:
            with conn.cursor() as cursor:
                clauses = []
                params = []
                if company_id:
                    clauses.append("company_id = %s")
                    params.append(company_id)
                if contact_id:
                    clauses.append("contact_id = %s")
                    params.append(contact_id)
                if email:
                    clauses.append("recipient_email = %s")
                    params.append(email.lower().strip())

                if not clauses:
                    return False

                sql = f"""
                SELECT 1 FROM outreach_messages 
                WHERE direction = 'outbound' AND ({' OR '.join(clauses)})
                LIMIT 1
                """
                cursor.execute(sql, tuple(params))
                return cursor.fetchone() is not None
        except Exception:
            return False
        finally:
            conn.close()

    def save_outreach_message(
        self,
        company_id: int,
        contact_id: int,
        subject: str,
        body_text: str,
        campaign_id: int | None = None,
        status: str = "queued",
        evidence_snapshot: dict[str, Any] | None = None,
        subject_variant: str | None = "A",
    ) -> int:
        """Saves a personalized outreach message in the queue."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                valid_contact_id = contact_id if (contact_id and contact_id > 0) else None
                if valid_contact_id:
                    cursor.execute("SELECT id FROM contacts WHERE id = %s", (valid_contact_id,))
                    if not cursor.fetchone():
                        valid_contact_id = None

                sql = """
                INSERT INTO outreach_messages (company_id, contact_id, subject, body_text, campaign_id, status, evidence_snapshot, subject_variant)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
                try:
                    cursor.execute(
                        sql,
                        (
                            company_id,
                            valid_contact_id,
                            subject,
                            body_text,
                            campaign_id,
                            status,
                            json.dumps(evidence_snapshot)
                            if evidence_snapshot is not None
                            else None,
                            subject_variant or "A",
                        ),
                    )
                except Exception as sql_err:
                    if "1452" in str(sql_err) or "foreign key" in str(sql_err).lower():
                        cursor.execute(
                            sql,
                            (
                                company_id,
                                None,
                                subject,
                                body_text,
                                campaign_id,
                                status,
                                json.dumps(evidence_snapshot)
                                if evidence_snapshot is not None
                                else None,
                                subject_variant or "A",
                            ),
                        )
                    else:
                        raise sql_err

                return cursor.lastrowid
        finally:
            conn.close()

    def prune_low_score_companies(self, min_score: float = 40.0) -> int:
        """
        Soft-archives companies whose latest opportunity_score is strictly below min_score.
        Preserves raw data and tech fingerprints for future model recalibration.
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                # Find all companies that have been scored below min_score
                sql_find = """
                SELECT DISTINCT c.id
                FROM companies c
                JOIN scores s ON s.company_id = c.id
                WHERE s.opportunity_score < %s
                  AND s.priority_tier != 'ignore'
                """
                cursor.execute(sql_find, (min_score,))
                rows = cursor.fetchall()
                if not rows:
                    return 0

                comp_ids = [r["id"] for r in rows]
                placeholders = ",".join(["%s"] * len(comp_ids))

                # Soft archive: Update score tier to 'ignore' to exclude from active outreach
                cursor.execute(
                    f"UPDATE scores SET priority_tier = 'ignore' WHERE company_id IN ({placeholders})",
                    tuple(comp_ids),
                )
                conn.commit()
                return len(comp_ids)
        finally:
            conn.close()

    def save_outreach_outcome(
        self,
        company_id: int,
        contact_id: int,
        initial_opportunity_score: float,
        company_fit_score: float,
        technology_gap_score: float,
        pain_signal_score: float,
        buying_signal_score: float,
        contact_quality_score: float,
        service_fit_score: float,
        source: str = "unknown",
        industry: str | None = None,
        message_id: int | None = None,
        opened: bool = False,
        replied: bool = False,
        meeting_booked: bool = False,
        closed_won: bool = False,
        deal_size_closed: float | None = None,
    ) -> int:
        """Records an outreach result to correlate predicted sub-scores against real-world conversions."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                sql = """
                INSERT INTO outreach_outcomes (
                    company_id, contact_id, message_id, source, industry,
                    initial_opportunity_score, company_fit_score, technology_gap_score,
                    pain_signal_score, buying_signal_score, contact_quality_score, service_fit_score,
                    opened, replied, meeting_booked, closed_won, deal_size_closed
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(
                    sql,
                    (
                        company_id,
                        contact_id,
                        message_id,
                        source,
                        industry,
                        initial_opportunity_score,
                        company_fit_score,
                        technology_gap_score,
                        pain_signal_score,
                        buying_signal_score,
                        contact_quality_score,
                        service_fit_score,
                        opened,
                        replied,
                        meeting_booked,
                        closed_won,
                        deal_size_closed,
                    ),
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def get_calibration_report(self) -> list[dict[str, Any]]:
        """
        Calculates empirical correlation between predicted sub-scores and actual reply/conversion rates.
        Used to calibrate provisional confidence weights with real data.
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                sql = """
                SELECT 
                    source,
                    COUNT(*) as total_outreaches,
                    AVG(initial_opportunity_score) as avg_opp_score,
                    AVG(buying_signal_score) as avg_buying_score,
                    AVG(technology_gap_score) as avg_tech_gap_score,
                    AVG(pain_signal_score) as avg_pain_score,
                    SUM(opened) as total_opened,
                    SUM(replied) as total_replied,
                    SUM(meeting_booked) as total_meetings,
                    SUM(closed_won) as total_closed,
                    ROUND((SUM(replied) / COUNT(*)) * 100, 2) as reply_rate_pct,
                    ROUND((SUM(closed_won) / COUNT(*)) * 100, 2) as close_rate_pct,
                    COALESCE(SUM(deal_size_closed), 0) as total_revenue_won
                FROM outreach_outcomes
                GROUP BY source
                ORDER BY total_outreaches DESC
                """
                cursor.execute(sql)
                return cursor.fetchall()
        finally:
            conn.close()


# Shared singleton instance
_mysql_instance: MySQLClient | None = None


def get_mysql_client() -> MySQLClient:
    global _mysql_instance
    if _mysql_instance is None:
        _mysql_instance = MySQLClient()
    return _mysql_instance

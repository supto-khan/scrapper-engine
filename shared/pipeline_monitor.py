"""
Nexidant Signal Engine — Pipeline Health Monitor & Alerting

Tracks execution metrics for each pipeline stage, persists run history
to MySQL, detects anomalies vs rolling 7-day average, and dispatches
alerts via Slack webhook or fallback email.
"""

import json
import logging
import os
import smtplib
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Any

import requests
from dotenv import load_dotenv

from shared.mysql_client import get_mysql_client

load_dotenv()
logger = logging.getLogger(__name__)


class StageContext:
    """
    Context object yielded by PipelineMonitor.track_stage().
    Records items processed/failed and custom metrics within a stage.
    """

    def __init__(self, stage_name: str, run_id: int):
        self.stage_name = stage_name
        self.run_id = run_id
        self.items_processed = 0
        self.items_failed = 0
        self.metrics: dict[str, Any] = {}
        self._start_time = time.time()

    def record(
        self,
        items_processed: int = 0,
        items_failed: int = 0,
        **extra_metrics,
    ):
        """Update stage counters and custom metrics."""
        self.items_processed += items_processed
        self.items_failed += items_failed
        self.metrics.update(extra_metrics)

    @property
    def elapsed_seconds(self) -> float:
        return round(time.time() - self._start_time, 2)


class PipelineMonitor:
    """
    Pipeline health monitor that tracks stage execution, detects anomalies,
    and dispatches alerts on failure or degradation via Telegram, Slack, or Email.
    """

    def __init__(self):
        self.mysql = get_mysql_client()
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or None
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID") or None
        self.slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL") or None
        self.alert_email = os.getenv("ALERT_EMAIL") or None
        self.smtp_host = os.getenv("SMTP_HOST") or None
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER") or None
        self.smtp_password = os.getenv("SMTP_PASSWORD") or None

    # ─── Stage Tracking ───────────────────────────────────────────────────

    def _create_run(self, stage_name: str) -> int:
        """Insert a 'running' record into pipeline_runs and return the id."""
        conn = self.mysql.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pipeline_runs (stage_name, status, started_at)
                    VALUES (%s, 'running', NOW())
                    """,
                    (stage_name,),
                )
                return cur.lastrowid
        finally:
            conn.close()

    def _finalize_run(
        self,
        run_id: int,
        status: str,
        duration_seconds: float,
        items_processed: int,
        items_failed: int,
        error_message: str | None,
        metrics: dict[str, Any] | None,
    ):
        """Update the pipeline_runs row with final results."""
        conn = self.mysql.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE pipeline_runs
                    SET status = %s,
                        finished_at = NOW(),
                        duration_seconds = %s,
                        items_processed = %s,
                        items_failed = %s,
                        error_message = %s,
                        metrics = %s
                    WHERE id = %s
                    """,
                    (
                        status,
                        duration_seconds,
                        items_processed,
                        items_failed,
                        error_message,
                        json.dumps(metrics) if metrics else None,
                        run_id,
                    ),
                )
        finally:
            conn.close()

    @contextmanager
    def track_stage(self, stage_name: str):
        """
        Context manager that tracks a pipeline stage's lifecycle.

        Usage:
            monitor = get_pipeline_monitor()
            with monitor.track_stage("intelligence") as stage:
                # ... pipeline logic ...
                stage.record(items_processed=10, items_failed=2)
        """
        run_id = self._create_run(stage_name)
        ctx = StageContext(stage_name, run_id)

        try:
            yield ctx

            # Determine status
            if ctx.items_failed > 0 and ctx.items_processed > 0:
                status = "partial"
            elif ctx.items_failed > 0 and ctx.items_processed == 0:
                status = "failed"
            else:
                status = "success"

            self._finalize_run(
                run_id=run_id,
                status=status,
                duration_seconds=ctx.elapsed_seconds,
                items_processed=ctx.items_processed,
                items_failed=ctx.items_failed,
                error_message=None,
                metrics=ctx.metrics,
            )

            # Check for anomalies on success/partial
            self._check_anomalies(stage_name, ctx)

            if status == "partial":
                logger.warning(
                    f"⚠️ Pipeline stage '{stage_name}' completed with partial failures: "
                    f"{ctx.items_processed} processed, {ctx.items_failed} failed "
                    f"({ctx.elapsed_seconds}s)"
                )

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            self._finalize_run(
                run_id=run_id,
                status="failed",
                duration_seconds=ctx.elapsed_seconds,
                items_processed=ctx.items_processed,
                items_failed=ctx.items_failed,
                error_message=error_msg[:2000],
                metrics=ctx.metrics,
            )

            # Send failure alert
            self._send_alert(
                title=f"🚨 Pipeline FAILURE: {stage_name}",
                message=(
                    f"Stage '{stage_name}' crashed after {ctx.elapsed_seconds}s.\n"
                    f"Processed: {ctx.items_processed} | Failed: {ctx.items_failed}\n"
                    f"Error: {type(e).__name__}: {e}"
                ),
                severity="critical",
            )

            raise  # Re-raise so the caller sees the exception

    # ─── Anomaly Detection ────────────────────────────────────────────────

    def _check_anomalies(self, stage_name: str, ctx: StageContext):
        """
        Compare today's metrics against a rolling 7-day average.
        Alert if any key metric drops more than 50%.
        """
        try:
            conn = self.mysql.get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            AVG(items_processed) as avg_processed,
                            AVG(duration_seconds) as avg_duration,
                            COUNT(*) as run_count
                        FROM pipeline_runs
                        WHERE stage_name = %s
                          AND status IN ('success', 'partial')
                          AND started_at > DATE_SUB(NOW(), INTERVAL 7 DAY)
                          AND id != %s
                        """,
                        (stage_name, ctx.run_id),
                    )
                    row = cur.fetchone()
            finally:
                conn.close()

            if not row or not row.get("run_count") or row["run_count"] < 3:
                return  # Not enough history to detect anomalies

            avg_processed = float(row["avg_processed"] or 0)
            if avg_processed > 5 and ctx.items_processed < avg_processed * 0.5:
                self._send_alert(
                    title=f"⚠️ Anomaly Detected: {stage_name}",
                    message=(
                        f"Items processed ({ctx.items_processed}) dropped >50% "
                        f"below 7-day average ({avg_processed:.0f}).\n"
                        f"This may indicate a data source outage or crawl failure."
                    ),
                    severity="warning",
                )
                # Mark as alerted
                conn2 = self.mysql.get_connection()
                try:
                    with conn2.cursor() as cur2:
                        cur2.execute(
                            "UPDATE pipeline_runs SET alerted = 1 WHERE id = %s",
                            (ctx.run_id,),
                        )
                finally:
                    conn2.close()

        except Exception as e:
            logger.warning(f"Anomaly detection failed for {stage_name}: {e}")

    # ─── Alert Dispatch ───────────────────────────────────────────────────

    def _send_alert(self, title: str, message: str, severity: str = "warning"):
        """Dispatches alert to Telegram, Slack webhook, and/or email. Always logs."""
        full_msg = f"{title}\n{message}"
        logger.warning(full_msg)

        emoji = "🚨" if severity == "critical" else "⚠️"

        # 1. Telegram bot alert
        if self.telegram_bot_token and self.telegram_chat_id:
            try:
                tg_text = f"{emoji} *{title}*\n\n{message}\n\n_Nexidant Signal Engine_"
                resp = requests.post(
                    f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage",
                    json={
                        "chat_id": self.telegram_chat_id,
                        "text": tg_text,
                        "parse_mode": "Markdown",
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    logger.info(f"✅ Telegram alert sent: {title}")
                else:
                    logger.warning(f"Telegram alert failed (HTTP {resp.status_code}): {resp.text[:100]}")
            except Exception as e:
                logger.warning(f"Telegram alert dispatch error: {e}")

        # 2. Slack webhook
        if self.slack_webhook_url:
            try:
                color = "#EF4444" if severity == "critical" else "#F59E0B"
                payload = {
                    "attachments": [
                        {
                            "color": color,
                            "title": f"{emoji} {title}",
                            "text": message,
                            "footer": "Nexidant Signal Engine",
                            "ts": int(time.time()),
                        }
                    ]
                }
                resp = requests.post(
                    self.slack_webhook_url,
                    json=payload,
                    timeout=10,
                )
                if resp.status_code == 200:
                    logger.info(f"✅ Slack alert sent: {title}")
                else:
                    logger.warning(f"Slack alert failed (HTTP {resp.status_code}): {resp.text[:100]}")
            except Exception as e:
                logger.warning(f"Slack alert dispatch error: {e}")

        # 3. Email fallback
        if self.alert_email and self.smtp_host and self.smtp_user and self.smtp_password:
            try:
                msg = MIMEText(message, "plain", "utf-8")
                msg["Subject"] = f"[Nexidant Signal] {title}"
                msg["From"] = self.smtp_user
                msg["To"] = self.alert_email

                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
                logger.info(f"✅ Email alert sent to {self.alert_email}: {title}")
            except Exception as e:
                logger.warning(f"Email alert dispatch error: {e}")

    # ─── Query Helpers ────────────────────────────────────────────────────

    def get_recent_runs(self, stage_name: str | None = None, limit: int = 10) -> list[dict]:
        """Returns recent pipeline runs, optionally filtered by stage."""
        conn = self.mysql.get_connection()
        try:
            with conn.cursor() as cur:
                if stage_name:
                    cur.execute(
                        "SELECT * FROM pipeline_runs WHERE stage_name = %s ORDER BY id DESC LIMIT %s",
                        (stage_name, limit),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT %s",
                        (limit,),
                    )
                return cur.fetchall()
        finally:
            conn.close()


# ─── Module Accessor ──────────────────────────────────────────────────────

_monitor_instance: PipelineMonitor | None = None


def get_pipeline_monitor() -> PipelineMonitor:
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = PipelineMonitor()
    return _monitor_instance

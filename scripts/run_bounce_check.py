#!/usr/bin/env python3
"""
Nexidant Signal Engine — Bounce Check Runner
Scans IMAP inbox for email bounces and auto-suppresses hard-bounced addresses.
Run daily (before outreach staging) or on-demand.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from outreach.bounce.bounce_detector import get_bounce_detector
from shared.pipeline_monitor import get_pipeline_monitor

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("run_bounce_check")


def run_bounce_check():
    monitor = get_pipeline_monitor()

    with monitor.track_stage("bounce_check") as stage:
        detector = get_bounce_detector()
        stats = detector.scan_and_suppress(days_back=7)

        stage.record(
            items_processed=stats["messages_scanned"],
            items_failed=stats["hard_bounces"] + stats["complaints"],
            hard_bounces=stats["hard_bounces"],
            soft_bounces=stats["soft_bounces"],
            complaints=stats["complaints"],
            emails_suppressed=stats["emails_suppressed"],
            promotions=stats["promotions"],
        )

        logger.info(
            f"📊 Bounce check summary: "
            f"Scanned {stats['messages_scanned']} | "
            f"Hard: {stats['hard_bounces']} | Soft: {stats['soft_bounces']} | "
            f"Complaints: {stats['complaints']} | "
            f"Suppressed: {stats['emails_suppressed']}"
        )


if __name__ == "__main__":
    run_bounce_check()

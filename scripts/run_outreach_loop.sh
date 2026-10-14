#!/bin/bash
# ==============================================================================
# Nexidant Signal - Continuous Outreach Staging & Maintenance Daemon
# Managed by Supervisor (Program: nexidant-outreach-engine).
#
# Runs independently from crawling & auditing:
# 1. Cleans duplicate outreach & suppresses bounced inboxes
# 2. Checks bounce inboxes for invalid addresses
# 3. Generates AI personalized copy & stages messages into queue (limit: 50)
# (Actual staggered 1/min sending is handled by cron outreach:send-scheduled)
# ==============================================================================

set -o pipefail

ENGINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ENGINE_DIR"

PYTHON="$ENGINE_DIR/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

# Run with nice -n 10
PY_RUN="nice -n 10 $PYTHON"

echo "🚀 [$(date '+%Y-%m-%d %H:%M:%S')] Nexidant Outreach Staging Daemon Initialized."
echo "📂 Working Directory: $ENGINE_DIR"
echo "🐍 Python Binary: $PYTHON (Priority: nice -n 10)"

CYCLE=1

while true; do
    CYCLE_START=$(date +%s)
    echo ""
    echo "================================================================================"
    echo "✉️  [$(date '+%Y-%m-%d %H:%M:%S')] Starting Outreach Staging Cycle #$CYCLE"
    echo "================================================================================"

    # Step 1: Clean duplicate outreach records
    echo "👉 [1/3] Cleaning duplicate outreach records..."
    $PY_RUN scripts/clean_duplicate_outreach.py || echo "⚠️ Warning: clean_duplicate_outreach failed, continuing..."

    # Step 2: Check bounce mailboxes & update suppression lists
    echo "👉 [2/3] Checking bounce mailboxes..."
    $PY_RUN scripts/run_bounce_check.py || echo "⚠️ Warning: run_bounce_check failed, continuing..."

    # Step 3: Generate AI personalized copy & stage messages for newly enriched leads
    echo "👉 [3/3] Generating AI outreach copy & staging queued messages (limit: 50, min_score: 50)..."
    $PY_RUN scripts/run_outreach.py --min-score 50.0 --limit 50 || echo "⚠️ Warning: run_outreach failed, continuing..."

    CYCLE_END=$(date +%s)
    DURATION=$((CYCLE_END - CYCLE_START))

    echo ""
    echo "================================================================================"
    echo "✅ [$(date '+%Y-%m-%d %H:%M:%S')] Completed Outreach Cycle #$CYCLE in ${DURATION}s."
    echo "⏸️  Resting for 45 seconds before checking for newly qualified leads..."
    echo "================================================================================"

    CYCLE=$((CYCLE + 1))
    sleep 45
done

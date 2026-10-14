#!/bin/bash
# ==============================================================================
# Nexidant Signal - Continuous Pipeline Orchestrator Daemon
# Runs the full discovery -> intelligence -> scoring -> enrichment -> outreach loop.
# Automatically restarts from Step 1 as soon as the previous cycle finishes.
# Managed by aaPanel Supervisor (Program: nexidant-pipeline).
# ==============================================================================

set -o pipefail

ENGINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ENGINE_DIR"

PYTHON="$ENGINE_DIR/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

# Run background workers with nice -n 10 so web (Nginx/PHP), MySQL, and SSH retain CPU priority
PY_RUN="nice -n 10 $PYTHON"

echo "🚀 [$(date '+%Y-%m-%d %H:%M:%S')] Nexidant Continuous Pipeline Daemon Initialized."
echo "📂 Working Directory: $ENGINE_DIR"
echo "🐍 Python Binary: $PYTHON (Priority: nice -n 10)"

CYCLE=1

while true; do
    CYCLE_START=$(date +%s)
    echo ""
    echo "================================================================================"
    echo "🔄 [$(date '+%Y-%m-%d %H:%M:%S')] Starting Pipeline Cycle #$CYCLE"
    echo "================================================================================"

    # Step 1: Clean duplicates & suppress bounces
    echo "👉 [1/6] Cleaning duplicate outreach & checking bounces..."
    $PY_RUN scripts/clean_duplicate_outreach.py || echo "⚠️ Warning: clean_duplicate_outreach failed, continuing..."
    $PY_RUN scripts/run_bounce_check.py || echo "⚠️ Warning: run_bounce_check failed, continuing..."

    # Step 2: B2B Directory Discovery (Clutch, GoodFirms, Yelp)
    echo "👉 [2/6] Running B2B directory discovery..."
    $PY_RUN scripts/run_discovery.py || echo "⚠️ Warning: run_discovery failed, continuing..."

    # Step 3: 360° Tech Intelligence, Speed Audit & Screenshots
    echo "👉 [3/6] Running tech intelligence, speed audit & screenshot analysis..."
    $PY_RUN scripts/run_intelligence.py || echo "⚠️ Warning: run_intelligence failed, continuing..."

    # Step 4: Lead Opportunity Scoring Engine
    echo "👉 [4/6] Running lead scoring engine..."
    $PY_RUN scripts/run_scoring.py --limit 1000 || echo "⚠️ Warning: run_scoring failed, continuing..."

    # Step 5: Decision Maker Email Enrichment (excludes .local)
    echo "👉 [5/6] Running decision maker email enrichment..."
    $PY_RUN scripts/run_enrichment.py || echo "⚠️ Warning: run_enrichment failed, continuing..."

    # Step 6: AI Outreach Copy Generation & Staging (Production Engine)
    echo "👉 [6/6] Generating personalized AI outreach copy & staging queued messages..."
    $PY_RUN scripts/run_outreach.py --min-score 50.0 --limit 50 || echo "⚠️ Warning: run_outreach failed, continuing..."

    CYCLE_END=$(date +%s)
    DURATION=$((CYCLE_END - CYCLE_START))

    echo ""
    echo "================================================================================"
    echo "✅ [$(date '+%Y-%m-%d %H:%M:%S')] Completed Pipeline Cycle #$CYCLE in ${DURATION}s."
    echo "⏸️  Resting for 30 seconds before immediately restarting from Step 1..."
    echo "================================================================================"

    CYCLE=$((CYCLE + 1))
    sleep 30
done

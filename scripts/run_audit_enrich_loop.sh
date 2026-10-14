#!/bin/bash
# ==============================================================================
# Nexidant Signal - Continuous Intelligence, Scoring & Enrichment Worker Daemon
# Managed by Supervisor (Program: nexidant-auditor-enricher).
#
# Processes uncrawled/pending_audit companies in safe continuous batches:
# 1. 360° Tech Intelligence, Speed Audit & Pain Detection (batches of 25)
# 2. Lead Opportunity Scoring Engine (re-scores newly audited leads)
# 3. Decision Maker Email & Phone Enrichment (Tier 1-6 with live verification)
# 4. Periodic B2B Directory Discovery (every 6th cycle)
# ==============================================================================

set -o pipefail

ENGINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ENGINE_DIR"

PYTHON="$ENGINE_DIR/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

# Run with nice -n 10 so web traffic (Nginx/PHP), MySQL, and SSH retain priority
PY_RUN="nice -n 10 $PYTHON"

echo "🚀 [$(date '+%Y-%m-%d %H:%M:%S')] Nexidant Auditor & Enricher Daemon Initialized."
echo "📂 Working Directory: $ENGINE_DIR"
echo "🐍 Python Binary: $PYTHON (Priority: nice -n 10)"

CYCLE=1

while true; do
    CYCLE_START=$(date +%s)
    echo ""
    echo "================================================================================"
    echo "🔍 [$(date '+%Y-%m-%d %H:%M:%S')] Starting Audit & Enrichment Cycle #$CYCLE"
    echo "================================================================================"

    # Step 1: Deep 360° Tech Intelligence, Speed Audit & Mobile Diagnostics
    # High-throughput batch of 100 with 5 concurrent network workers (PDF generated on-demand at outreach)
    echo "👉 [1/3] Running high-speed tech intelligence audits on pending companies (limit: 100, workers: 5)..."
    $PY_RUN scripts/run_intelligence.py --limit 100 --workers 5 --no-pdf || echo "⚠️ Warning: run_intelligence failed, continuing..."

    # Step 2: Lead Opportunity Scoring Engine
    echo "👉 [2/3] Running lead scoring engine on newly audited leads (limit: 1000)..."
    $PY_RUN scripts/run_scoring.py --limit 1000 || echo "⚠️ Warning: run_scoring failed, continuing..."

    # Step 3: Decision Maker Email & Phone Enrichment (uses all 4 methods + live SMTP check)
    echo "👉 [3/3] Running decision maker enrichment on high-priority leads (limit: 30, min_score: 40)..."
    $PY_RUN scripts/run_enrichment.py --limit 30 --min-score 40.0 || echo "⚠️ Warning: run_enrichment failed, continuing..."

    # Optional Periodic Discovery: Run B2B directory crawl once every 6 cycles (~every 10-15 minutes)
    if [ $((CYCLE % 6)) -eq 0 ]; then
        echo "🌐 [Periodic] Running B2B directory discovery (target: 40 leads)..."
        $PY_RUN scripts/run_discovery.py --target 40 || echo "⚠️ Warning: run_discovery failed, continuing..."
    fi

    CYCLE_END=$(date +%s)
    DURATION=$((CYCLE_END - CYCLE_START))

    echo ""
    echo "================================================================================"
    echo "✅ [$(date '+%Y-%m-%d %H:%M:%S')] Completed Audit & Enrichment Cycle #$CYCLE in ${DURATION}s."
    echo "⏸️  Resting for 15 seconds before next batch..."
    echo "================================================================================"

    CYCLE=$((CYCLE + 1))
    sleep 15
done

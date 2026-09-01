#!/bin/bash
# Nexidant Signal - Complete Daily Pipeline Runner
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ENGINE_DIR"

# Detect Python executable
if [ -f "$ENGINE_DIR/venv/bin/python" ]; then
    PYTHON_EXEC="$ENGINE_DIR/venv/bin/python"
elif [ -f "/opt/homebrew/anaconda3/envs/signal-engine/bin/python" ]; then
    PYTHON_EXEC="/opt/homebrew/anaconda3/envs/signal-engine/bin/python"
else
    PYTHON_EXEC="python3"
fi

echo "🚀 [1/8] Cleaning Redundant Records..."
$PYTHON_EXEC scripts/clean_duplicate_outreach.py

echo "🔄 [2/8] Checking Email Bounces & Auto-Suppressing (Sender Reputation Guard)..."
$PYTHON_EXEC scripts/run_bounce_check.py

echo "🔍 [3/8] Running Directory Discovery (Clutch, GoodFirms, Yelp)..."
$PYTHON_EXEC scripts/run_discovery.py

echo "📍 [4/8] Running Google Maps Discovery (Local & No-Website Leads)..."
$PYTHON_EXEC scripts/run_google_maps_crawler.py --queries 8

echo "⚡ [5/8] Running Technical & Performance Intelligence (360° Diagnostics + Rate-Limiting)..."
$PYTHON_EXEC scripts/run_intelligence.py

echo "🎯 [6/8] Running Lead Scoring..."
$PYTHON_EXEC scripts/run_scoring.py

echo "📧 [7/8] Running Decision-Maker Email Enrichment..."
$PYTHON_EXEC scripts/run_enrichment.py

echo "✍️ [8/8] Generating & Staging Personalized AI Copy & PDFs..."
$PYTHON_EXEC scripts/run_offline_copy_batch.py

echo "🎉 All daily intelligence, health monitoring, and outreach staging completed successfully!"

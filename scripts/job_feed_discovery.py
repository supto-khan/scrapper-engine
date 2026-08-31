#!/usr/bin/env python3
"""
Convenience CLI runner for Job Feed Intent Discovery.
Discovers high-intent commercial buyers actively recruiting developers.
"""
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from discovery.hiring.job_feed_discovery import get_job_board_discovery

if __name__ == "__main__":
    discovery = get_job_board_discovery()
    ingested = discovery.discover_hiring_leads()
    print(f"\n🎉 Finished! Ingested {ingested} active hiring buyer leads.")

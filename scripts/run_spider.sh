#!/usr/bin/env bash
# ==============================================================================
# Signal Engine Spider Runner
# Usage: ./scripts/run_spider.sh <spider_name> [optional_domain]
# Example: ./scripts/run_spider.sh clutch_spider
#          ./scripts/run_spider.sh company_site_spider example.com
# ==============================================================================

set -e

SPIDER_NAME=${1:-"company_site_spider"}
TARGET_DOMAIN=$2

if [ -n "$TARGET_DOMAIN" ]; then
    echo "Running spider: $SPIDER_NAME for domain: $TARGET_DOMAIN"
    scrapy crawl "$SPIDER_NAME" -a "target_domain=$TARGET_DOMAIN"
else
    echo "Running spider: $SPIDER_NAME"
    scrapy crawl "$SPIDER_NAME"
fi

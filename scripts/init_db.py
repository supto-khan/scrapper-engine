#!/usr/bin/env python3
"""
Signal Engine — Database Migration / Schema Initializer
Creates the `nexidant_signal` database (if it doesn't exist) and initializes all tables
from db/schema.sql into MySQL/MariaDB (XAMPP / native VPS setup).
"""
import os
import sys
import logging

# Ensure project root is in sys.path when running scripts directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.mysql_client import get_mysql_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("init_db")


def init_database():
    schema_path = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")
    schema_path = os.path.abspath(schema_path)

    client = get_mysql_client()

    logger.info(f"Connecting to MySQL server at {client.host}:{client.port} as user '{client.user}'...")
    if not client.ping():
        logger.error(
            f"Could not connect to MySQL at {client.host}:{client.port}. "
            "Please ensure XAMPP MySQL is started in the XAMPP Control Panel and credentials in .env are correct."
        )
        sys.exit(1)

    logger.info(f"Initializing database `{client.db_name}` and applying schema from {schema_path}...")
    try:
        client.init_schema(schema_path)
        logger.info(f"✅ Successfully initialized database `{client.db_name}` with all tables:")
        logger.info("   - companies")
        logger.info("   - technologies")
        logger.info("   - raw_company_data")
        logger.info("   - audits")
        logger.info("   - signals")
        logger.info("   - opportunities")
        logger.info("   - scores")
        logger.info("   - contacts")
        logger.info("   - outreach_campaigns")
        logger.info("   - outreach_messages")
    except Exception as e:
        logger.error(f"Failed to apply database schema: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    init_database()

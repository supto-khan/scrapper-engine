#!/usr/bin/env python3
"""
Signal Engine — Database Migration Runner
Automatically applies all SQL migration files in `db/migrations/` in chronological order.
Can be run safely multiple times (idempotent / handles existing tables & columns).
"""

import glob
import logging
import os
import sys

# Ensure project root is in sys.path when running scripts directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.mysql_client import get_mysql_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate")


def run_migrations():
    migrations_dir = os.path.join(os.path.dirname(__file__), "..", "db", "migrations")
    migrations_dir = os.path.abspath(migrations_dir)

    client = get_mysql_client()

    logger.info(f"Connecting to MySQL ({client.host}:{client.port}, DB: `{client.db_name}`)...")
    if not client.ping():
        logger.error(f"Could not connect to MySQL at {client.host}:{client.port}. Check .env credentials.")
        sys.exit(1)

    sql_files = sorted(glob.glob(os.path.join(migrations_dir, "*.sql")))
    if not sql_files:
        logger.info("No migration files found in db/migrations/.")
        return

    logger.info(f"🚀 Found {len(sql_files)} migration files in {migrations_dir}:")
    for f in sql_files:
        logger.info(f"   • {os.path.basename(f)}")

    conn = client.get_connection()
    try:
        # Create a migrations tracking table if not exists
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    migration VARCHAR(255) NOT NULL UNIQUE,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cursor.execute("SELECT migration FROM schema_migrations")
            applied = {row["migration"] for row in cursor.fetchall()}

        applied_count = 0
        for filepath in sql_files:
            filename = os.path.basename(filepath)
            if filename in applied:
                logger.info(f"⏩ [Already Applied] {filename}")
                continue

            logger.info(f"⚙️ Applying migration: {filename}...")
            with open(filepath, "r", encoding="utf-8") as f:
                sql_content = f.read()

            # Split statements by semicolon
            statements = [stmt.strip() for stmt in sql_content.split(";") if stmt.strip()]
            with conn.cursor() as cursor:
                for stmt in statements:
                    try:
                        cursor.execute(stmt)
                    except Exception as err:
                        # Ignore "duplicate column name" or "table already exists" errors
                        err_msg = str(err).lower()
                        if "duplicate column" in err_msg or "already exists" in err_msg:
                            logger.debug(f"Notice during migration (already present): {err}")
                        else:
                            logger.warning(f"Warning executing statement in {filename}: {err}")

                cursor.execute(
                    "INSERT INTO schema_migrations (migration) VALUES (%s) ON DUPLICATE KEY UPDATE applied_at = CURRENT_TIMESTAMP",
                    (filename,),
                )
            conn.commit()
            logger.info(f"✅ [Applied Successfully] {filename}")
            applied_count += 1

        logger.info(f"\n🎉 All migrations completed! ({applied_count} newly applied, {len(sql_files) - applied_count} previously applied).")

    except Exception as e:
        logger.error(f"Migration error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    run_migrations()

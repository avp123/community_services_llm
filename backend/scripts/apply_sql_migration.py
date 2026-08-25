#!/usr/bin/env python3
"""Apply a SQL migration file to a Postgres database (e.g. Azure).

Usage:
  export AZURE_PROD_DATABASE_URL='postgresql://...'
  python backend/scripts/apply_sql_migration.py backend/migrations/006_monthly_azure_chat_tokens.sql

Or (avoid shell history):
  echo 'postgresql://...' > backend/.secrets/azure_database_url
  chmod 600 backend/.secrets/azure_database_url
  python backend/scripts/apply_sql_migration.py backend/migrations/006_monthly_azure_chat_tokens.sql \\
      --url-file backend/.secrets/azure_database_url
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a SQL migration file against Postgres.")
    parser.add_argument(
        "migration_sql",
        type=Path,
        help="Path to .sql file (e.g. backend/migrations/006_monthly_azure_chat_tokens.sql)",
    )
    parser.add_argument(
        "--url-file",
        type=Path,
        help="File containing connection URI on a single line (recommended).",
    )
    parser.add_argument(
        "--env-var",
        default="AZURE_PROD_DATABASE_URL",
        metavar="NAME",
        help="Env var holding the URI if --url-file is omitted (default: AZURE_PROD_DATABASE_URL).",
    )
    args = parser.parse_args()

    if args.url_file:
        if not args.url_file.is_file():
            print(f"ERROR: --url-file not found: {args.url_file}", file=sys.stderr)
            return 1
        url = args.url_file.read_text().strip()
    else:
        url = os.environ.get(args.env_var, "").strip()
        if not url:
            print(
                f"ERROR: Set {args.env_var} or pass --url-file.",
                file=sys.stderr,
            )
            return 1

    sql_path = args.migration_sql
    if not sql_path.is_file():
        print(f"ERROR: migration file not found: {sql_path}", file=sys.stderr)
        return 1

    sql = sql_path.read_text()
    try:
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"OK: applied {sql_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

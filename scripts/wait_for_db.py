#!/usr/bin/env python3
"""Wait for PostgreSQL database to be ready for connections.

Waits for the database specified in DATABASE_URL to accept connections.
Optionally waits for a specific table to exist using --wait-for-table.

Never prints the database password.
Exit code 0 on success, 1 on timeout or error.
"""

import argparse
import os
import sys
import time

try:
    import psycopg
except ImportError:
    print("ERROR: psycopg is required. Install with: pip install psycopg[binary]")
    sys.exit(1)


def parse_database_url(url: str) -> dict:
    """Parse DATABASE_URL into connection parameters."""
    # Example: postgresql://user:password@localhost:5432/dbname
    if not url.startswith("postgresql://"):
        raise ValueError("DATABASE_URL must start with postgresql://")

    url = url[len("postgresql://") :]

    # Split auth from host
    if "@" in url:
        auth, hostdb = url.rsplit("@", 1)
        if ":" in auth:
            user, password = auth.split(":", 1)
        else:
            user = auth
            password = None
    else:
        user = None
        password = None
        hostdb = url

    # Split host from db
    if "/" in hostdb:
        host, dbname = hostdb.rsplit("/", 1)
    else:
        host = hostdb
        dbname = None

    # Split port from host
    if ":" in host:
        hostname, port = host.rsplit(":", 1)
        try:
            port = int(port)
        except ValueError:
            port = 5432
    else:
        hostname = host
        port = 5432

    return {
        "host": hostname or "localhost",
        "port": port,
        "user": user or "postgres",
        "password": password,
        "dbname": dbname or "postgres",
    }


def wait_for_connection(url: str, timeout: float = 30.0, interval: float = 1.0) -> bool:
    """Wait for database to accept connections.

    Args:
        url: DATABASE_URL connection string
        timeout: Maximum time to wait in seconds
        interval: Time between connection attempts in seconds

    Returns:
        True if connection successful, False on timeout
    """
    params = parse_database_url(url)
    start = time.time()

    while time.time() - start < timeout:
        try:
            with psycopg.connect(
                host=params["host"],
                port=params["port"],
                user=params["user"],
                password=params["password"],
                dbname=params["dbname"],
                connect_timeout=5,
            ):
                db_url = f"{params['host']}:{params['port']}/{params['dbname']}"
                print(f"✓ Database is ready at {db_url}")
                return True
        except psycopg.Error as e:
            elapsed = time.time() - start
            if elapsed < timeout:
                err_type = type(e).__name__
                print(f"  Waiting for database... ({elapsed:.1f}s/{timeout:.1f}s) {err_type}")
            time.sleep(interval)

    print(f"✗ Database did not accept connections within {timeout}s")
    return False


def wait_for_table(url: str, table_name: str, timeout: float = 30.0, interval: float = 1.0) -> bool:
    """Wait for a specific table to exist.

    Args:
        url: DATABASE_URL connection string
        table_name: Table name to check
        timeout: Maximum time to wait in seconds
        interval: Time between checks in seconds

    Returns:
        True if table exists, False on timeout
    """
    params = parse_database_url(url)
    start = time.time()

    while time.time() - start < timeout:
        try:
            with psycopg.connect(
                host=params["host"],
                port=params["port"],
                user=params["user"],
                password=params["password"],
                dbname=params["dbname"],
                connect_timeout=5,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = %s AND table_schema = 'public'
                        """,
                        (table_name,),
                    )
                    if cur.fetchone():
                        print(f"✓ Table '{table_name}' is ready")
                        return True

            elapsed = time.time() - start
            if elapsed < timeout:
                print(f"  Waiting for table '{table_name}'... ({elapsed:.1f}s/{timeout:.1f}s)")
            time.sleep(interval)
        except psycopg.Error as e:
            elapsed = time.time() - start
            if elapsed < timeout:
                err_type = type(e).__name__
                print(f"  Waiting for table check... ({elapsed:.1f}s/{timeout:.1f}s) {err_type}")
            time.sleep(interval)

    print(f"✗ Table '{table_name}' did not exist within {timeout}s")
    return False


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Wait for PostgreSQL database to be ready.")
    parser.add_argument(
        "--wait-for-table",
        type=str,
        default=None,
        help="Table name to wait for (optional)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Timeout in seconds (default: 30)",
    )
    args = parser.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable is not set")
        return 1

    # Wait for database connection
    if not wait_for_connection(db_url, timeout=args.timeout):
        return 1

    # Optionally wait for table
    if args.wait_for_table:
        if not wait_for_table(db_url, args.wait_for_table, timeout=args.timeout):
            return 1

    print("✓ Database is ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())

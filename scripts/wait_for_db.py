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
import urllib.parse

try:
    import psycopg
except ImportError:
    print("ERROR: psycopg is required. Install with: pip install psycopg[binary]")
    sys.exit(1)


def parse_database_url(url: str) -> dict:
    """Parse DATABASE_URL into connection parameters using urllib.parse.

    Supports schemes: postgresql, postgres, postgresql+psycopg, postgresql+psycopg_async.
    Query parameters (e.g. sslmode, sslrootcert, connect_timeout) are preserved.
    """
    # Handle schemes with underscores (like postgresql+psycopg_async) which urllib.parse
    # doesn't recognize due to RFC 3986 restrictions. We normalize them first.
    normalized_url = url
    if "postgresql+psycopg_async://" in url:
        # Replace with a RFC-compliant scheme for parsing, then validate
        normalized_url = url.replace("postgresql+psycopg_async://", "postgresql+psycopg-async://")
        scheme_map = {"postgresql+psycopg-async": "postgresql+psycopg_async"}
    elif "postgresql+psycopg://" in url:
        scheme_map = {"postgresql+psycopg": "postgresql+psycopg"}
        normalized_url = url
    else:
        scheme_map = {}

    parsed = urllib.parse.urlparse(normalized_url)

    # Validate scheme (use original scheme names)
    valid_schemes = (
        "postgresql",
        "postgres",
        "postgresql+psycopg",
        "postgresql+psycopg_async",
    )
    original_scheme = scheme_map.get(parsed.scheme, parsed.scheme)
    if original_scheme not in valid_schemes:
        raise ValueError(
            f"DATABASE_URL scheme must be one of {valid_schemes}, got {original_scheme}"
        )

    # Extract and decode user/password
    username = urllib.parse.unquote(parsed.username or "postgres")
    password = urllib.parse.unquote(parsed.password) if parsed.password else None

    # Extract hostname and port
    hostname = parsed.hostname or "localhost"
    port = parsed.port or 5432

    # Extract database name
    dbname = parsed.path.lstrip("/") or "postgres"

    # Parse query string into dict, keeping all parameters
    query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    # Flatten single-value parameters (parse_qs returns lists)
    query_dict = {k: v[0] if len(v) == 1 else v for k, v in query_params.items()}

    return {
        "host": hostname,
        "port": port,
        "user": username,
        "password": password,
        "dbname": dbname,
        "query_params": query_dict,
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
            # Build connection kwargs
            conn_kwargs = {
                "host": params["host"],
                "port": params["port"],
                "user": params["user"],
                "password": params["password"],
                "dbname": params["dbname"],
                "connect_timeout": 5,
            }
            # Add query parameters (e.g. sslmode, sslrootcert, etc.)
            conn_kwargs.update(params.get("query_params", {}))

            with psycopg.connect(**conn_kwargs):
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
            # Build connection kwargs
            conn_kwargs = {
                "host": params["host"],
                "port": params["port"],
                "user": params["user"],
                "password": params["password"],
                "dbname": params["dbname"],
                "connect_timeout": 5,
            }
            # Add query parameters (e.g. sslmode, sslrootcert, etc.)
            conn_kwargs.update(params.get("query_params", {}))

            with psycopg.connect(**conn_kwargs) as conn:
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

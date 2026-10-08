"""Write the API's OpenAPI document to a file.

Used by `npm run gen:api` in apps/web to generate the web client types. It needs the
API's Python environment (the same one that runs uvicorn).

Usage:
    python apps/api/scripts/export_openapi.py <output-path>

DATABASE_URL and JWT_SECRET are set to dummy values when they are not set, because the
settings are read when the app is created. Nothing connects to the database.
"""

import json
import os
import sys
from pathlib import Path

DUMMY_DATABASE_URL = "postgresql://export:export@localhost:5432/export"
DUMMY_JWT_SECRET = "openapi-export-only-not-a-secret-000000"


def main(argv: list[str]) -> int:
    """Write the OpenAPI JSON to argv[1]. Returns the process exit code."""
    if len(argv) != 2:
        print("usage: export_openapi.py <output-path>", file=sys.stderr)
        return 2

    os.environ.setdefault("DATABASE_URL", DUMMY_DATABASE_URL)
    os.environ.setdefault("JWT_SECRET", DUMMY_JWT_SECRET)

    from app.main import create_app

    app = create_app()
    output = Path(argv[1])
    output.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

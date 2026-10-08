"""Canonical ID generation and parsing for legal documents."""

import re
from datetime import date


def instrument_id(code: str) -> str:
    """Generate canonical ID for an instrument.

    Args:
        code: Instrument code (e.g., "CGST_ACT").

    Returns:
        Canonical ID (e.g., "inst:CGST_ACT").

    Raises:
        ValueError: If code is empty or invalid.
    """
    if not code or not isinstance(code, str):
        raise ValueError(f"Invalid instrument code: {code}")

    code = code.strip()
    if not code:
        raise ValueError("Instrument code cannot be empty")

    # Validate basic format: alphanumeric and underscores
    if not re.match(r"^[A-Z0-9_]+$", code):
        raise ValueError(f"Invalid instrument code format: {code}")

    return f"inst:{code}"


def provision_id(instrument_code: str, path: str) -> str:
    """Generate canonical ID for a provision.

    Args:
        instrument_code: Instrument code (e.g., "CGST_ACT").
        path: Provision path (e.g., "s16.2.c").

    Returns:
        Canonical ID (e.g., "prov:CGST_ACT:s16.2.c").

    Raises:
        ValueError: If inputs are invalid.
    """
    if not instrument_code or not isinstance(instrument_code, str):
        raise ValueError(f"Invalid instrument code: {instrument_code}")

    if not path or not isinstance(path, str):
        raise ValueError(f"Invalid provision path: {path}")

    instrument_code = instrument_code.strip()
    path = path.strip()

    if not instrument_code or not path:
        raise ValueError("Instrument code and path cannot be empty")

    # Validate instrument code format
    if not re.match(r"^[A-Z0-9_]+$", instrument_code):
        raise ValueError(f"Invalid instrument code format: {instrument_code}")

    # Validate path format: s/r followed by numbers and dots, with optional letters
    # Examples: s16, s16.2, s16.2.c, s74A, r36.4
    if not re.match(r"^[sr]\d+[a-z]?(?:\.\d+[a-z]?)*(?:\.\w+)*$", path, re.IGNORECASE):
        raise ValueError(f"Invalid provision path format: {path}")

    return f"prov:{instrument_code}:{path}"


def notification_id(series: str, number: str | int, year: str | int) -> str:
    """Generate canonical ID for a notification.

    Args:
        series: Series code (e.g., "CT", "CT(R)"), normalized through aliases.
        number: Notification number.
        year: Year (2017, 2022, etc.).

    Returns:
        Canonical ID (e.g., "ntf:CT(R):11/2017").

    Raises:
        ValueError: If inputs are invalid.
    """
    if not series or not isinstance(series, str):
        raise ValueError(f"Invalid series: {series}")

    if number is None or (not isinstance(number, (int, str))):
        raise ValueError(f"Invalid notification number: {number}")

    if year is None or (not isinstance(year, (int, str))):
        raise ValueError(f"Invalid year: {year}")

    series = series.strip()
    number = str(number).strip()
    year = str(year).strip()

    if not series or not number or not year:
        raise ValueError("Series, number, and year cannot be empty")

    # Validate series format (alphanumeric, parentheses, but no special chars)
    if not re.match(r"^[A-Z0-9()\s-]+$", series):
        raise ValueError(f"Invalid series format: {series}")

    # Validate number and year are numeric
    if not re.match(r"^\d+$", number):
        raise ValueError(f"Notification number must be numeric: {number}")

    if not re.match(r"^\d{4}$", year):
        raise ValueError(f"Year must be 4 digits: {year}")

    return f"ntf:{series}:{number}/{year}"


def circular_id(a: str | int, b: str | int, year: str | int) -> str:
    """Generate canonical ID for a circular.

    Circular IDs are typically formatted as: circular_id/sub_id/year

    Args:
        a: First number component (main circular number).
        b: Second number component (sub-circular number).
        year: Year.

    Returns:
        Canonical ID (e.g., "cir:183/15/2022").

    Raises:
        ValueError: If inputs are invalid.
    """
    if a is None or b is None or year is None:
        raise ValueError("All components of circular ID must be provided")

    a = str(a).strip()
    b = str(b).strip()
    year = str(year).strip()

    if not a or not b or not year:
        raise ValueError("Circular ID components cannot be empty")

    # Validate all components are numeric
    if not re.match(r"^\d+$", a):
        raise ValueError(f"Circular first number must be numeric: {a}")

    if not re.match(r"^\d+$", b):
        raise ValueError(f"Circular second number must be numeric: {b}")

    if not re.match(r"^\d{4}$", year):
        raise ValueError(f"Year must be 4 digits: {year}")

    return f"cir:{a}/{b}/{year}"


def instruction_id(number: str | int, year: str | int) -> str:
    """Generate canonical ID for an instruction.

    Args:
        number: Instruction number.
        year: Year.

    Returns:
        Canonical ID (e.g., "ins:123/2022").

    Raises:
        ValueError: If inputs are invalid.
    """
    if number is None or year is None:
        raise ValueError("Number and year must be provided")

    number = str(number).strip()
    year = str(year).strip()

    if not number or not year:
        raise ValueError("Number and year cannot be empty")

    if not re.match(r"^\d+$", number):
        raise ValueError(f"Instruction number must be numeric: {number}")

    if not re.match(r"^\d{4}$", year):
        raise ValueError(f"Year must be 4 digits: {year}")

    return f"ins:{number}/{year}"


def order_id(number: str | int, year: str | int) -> str:
    """Generate canonical ID for an order.

    Args:
        number: Order number.
        year: Year.

    Returns:
        Canonical ID (e.g., "ord:456/2022").

    Raises:
        ValueError: If inputs are invalid.
    """
    if number is None or year is None:
        raise ValueError("Number and year must be provided")

    number = str(number).strip()
    year = str(year).strip()

    if not number or not year:
        raise ValueError("Number and year cannot be empty")

    if not re.match(r"^\d+$", number):
        raise ValueError(f"Order number must be numeric: {number}")

    if not re.match(r"^\d{4}$", year):
        raise ValueError(f"Year must be 4 digits: {year}")

    return f"ord:{number}/{year}"


def judgement_id(court_code: str, case_number: str, decision_date: str | date) -> str:
    """Generate canonical ID for a judgement.

    Args:
        court_code: Court code (e.g., "SC", "HC-KA").
        case_number: Case number (e.g., "2023/123/SC").
        decision_date: Decision date (YYYY-MM-DD format or date object).

    Returns:
        Canonical ID (e.g., "jdg:SC:2023/123/SC:2023-10-08").

    Raises:
        ValueError: If inputs are invalid.
    """
    if not court_code or not isinstance(court_code, str):
        raise ValueError(f"Invalid court code: {court_code}")

    if not case_number or not isinstance(case_number, str):
        raise ValueError(f"Invalid case number: {case_number}")

    if decision_date is None:
        raise ValueError("Decision date must be provided")

    court_code = court_code.strip().upper()
    case_number = case_number.strip()

    if not court_code or not case_number:
        raise ValueError("Court code and case number cannot be empty")

    # Normalize case number: uppercase, remove whitespace, unify dashes
    normalized_case = case_number.upper()
    normalized_case = re.sub(r"\s+", "", normalized_case)
    # Keep slashes but normalize dashes
    normalized_case = re.sub(r"[–—−‐-]", "-", normalized_case)

    # Validate court code format (e.g., SC, HC, HC-KA, GSTAT - up to 5 letters)
    if not re.match(r"^[A-Z]{2,5}(?:-[A-Z]{2})?$", court_code):
        raise ValueError(f"Invalid court code format: {court_code}")

    # Parse and validate decision date
    if isinstance(decision_date, date):
        date_str = decision_date.isoformat()
    else:
        decision_date = str(decision_date).strip()
        # Validate YYYY-MM-DD format
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", decision_date):
            raise ValueError(f"Invalid date format (expected YYYY-MM-DD): {decision_date}")
        date_str = decision_date

    return f"jdg:{court_code}:{normalized_case}:{date_str}"


def parse_id(canonical: str) -> dict[str, str]:
    """Parse a canonical ID and return its components.

    Args:
        canonical: Canonical ID string.

    Returns:
        Dictionary with ID components. Keys depend on ID type:
        - instrument: {"type": "instrument", "code": str}
        - provision: {"type": "provision", "instrument_code": str, "path": str}
        - notification: {"type": "notification", "series": str, "number": str, "year": str}
        - circular: {"type": "circular", "a": str, "b": str, "year": str}
        - instruction: {"type": "instruction", "number": str, "year": str}
        - order: {"type": "order", "number": str, "year": str}
        - judgement: {"type": "judgement", "court": str, "case": str, "date": str}

    Raises:
        ValueError: If the ID format is invalid.
    """
    if not canonical or not isinstance(canonical, str):
        raise ValueError(f"Invalid canonical ID: {canonical}")

    canonical = canonical.strip()

    if not canonical:
        raise ValueError("Canonical ID cannot be empty")

    # Institution: inst:<code>
    if canonical.startswith("inst:"):
        code = canonical[5:].strip()
        if not code:
            raise ValueError("Invalid instrument ID: missing code")
        return {"type": "instrument", "code": code}

    # Provision: prov:<instrument_code>:<path>
    if canonical.startswith("prov:"):
        parts = canonical[5:].split(":")
        if len(parts) != 2:
            raise ValueError("Invalid provision ID: expected 2 parts")
        instrument_code, path = parts
        if not instrument_code or not path:
            raise ValueError("Invalid provision ID: empty components")
        return {"type": "provision", "instrument_code": instrument_code, "path": path}

    # Notification: ntf:<series>:<number>/<year>
    if canonical.startswith("ntf:"):
        parts = canonical[4:].split(":")
        if len(parts) != 2:
            raise ValueError("Invalid notification ID: expected 2 parts after ntf:")
        series, number_year = parts
        # Parse number/year
        match = re.match(r"^(\d+)/(\d{4})$", number_year)
        if not match:
            raise ValueError(f"Invalid notification ID: expected number/year format: {number_year}")
        number, year = match.groups()
        if not series:
            raise ValueError("Invalid notification ID: empty series")
        return {"type": "notification", "series": series, "number": number, "year": year}

    # Circular: cir:<a>/<b>/<year>
    if canonical.startswith("cir:"):
        parts = canonical[4:].split("/")
        if len(parts) != 3:
            raise ValueError("Invalid circular ID: expected a/b/year format")
        a, b, year = parts
        if not all([a, b, year]):
            raise ValueError("Invalid circular ID: empty components")
        return {"type": "circular", "a": a, "b": b, "year": year}

    # Instruction: ins:<number>/<year>
    if canonical.startswith("ins:"):
        parts = canonical[4:].split("/")
        if len(parts) != 2:
            raise ValueError("Invalid instruction ID: expected number/year format")
        number, year = parts
        if not number or not year:
            raise ValueError("Invalid instruction ID: empty components")
        return {"type": "instruction", "number": number, "year": year}

    # Order: ord:<number>/<year>
    if canonical.startswith("ord:"):
        parts = canonical[4:].split("/")
        if len(parts) != 2:
            raise ValueError("Invalid order ID: expected number/year format")
        number, year = parts
        if not number or not year:
            raise ValueError("Invalid order ID: empty components")
        return {"type": "order", "number": number, "year": year}

    # Judgement: jdg:<court>:<case>:<date>
    if canonical.startswith("jdg:"):
        parts = canonical[4:].split(":")
        if len(parts) < 3:
            raise ValueError("Invalid judgement ID: expected court:case:date format")
        court = parts[0]
        # Case number may contain colons (e.g., "2023:123:SC"), so join from index 1 to -1
        case = ":".join(parts[1:-1])
        date_str = parts[-1]
        if not court or not case or not date_str:
            raise ValueError("Invalid judgement ID: empty components")
        return {"type": "judgement", "court": court, "case": case, "date": date_str}

    raise ValueError(f"Unknown canonical ID format: {canonical}")


def is_valid_id(s: str) -> bool:
    """Check if a string is a valid canonical ID.

    Args:
        s: String to check.

    Returns:
        True if valid, False otherwise.
    """
    if not isinstance(s, str) or not s.strip():
        return False

    try:
        parse_id(s)
        return True
    except ValueError:
        return False

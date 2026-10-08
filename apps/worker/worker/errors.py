"""Exceptions that tell the runner whether a failed job may be retried."""


class PermanentError(Exception):
    """A handler failure that retrying cannot fix (bad input, missing file, refused URL)."""

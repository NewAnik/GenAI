"""Domain-agnostic exceptions the router maps to HTTP status codes and to the
`{"error":{"code","message"}}` envelope's `code` — this `code` is what
wrapped-and-more-admin/src/lib/queries.ts's `describeError` matches on (replacing the old
Postgres-numeric-error-code mapping PostgREST produced), so it's carried on the exception itself
rather than inferred from the exception's class alone."""
from __future__ import annotations


class ValidationError(Exception):
    def __init__(self, message: str, code: str = "validation_error"):
        super().__init__(message)
        self.code = code


class NotFoundError(Exception):
    def __init__(self, message: str = "not found", code: str = "not_found"):
        super().__init__(message)
        self.code = code


class ConflictError(Exception):
    """A Postgres constraint the write violated (unique/FK) — 409, not 422, since the request
    was well-formed and only failed against the current state of the data."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code

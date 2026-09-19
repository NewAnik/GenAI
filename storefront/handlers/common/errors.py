"""Domain-agnostic exceptions the router maps to HTTP status codes. Order-domain-specific
conflicts (EmptyCartError, InsufficientStockError, OrderNotCancellableError, ...) are mapped
explicitly inside each route function instead, since they need different statuses (400 vs
409) depending on context — mirroring how the original FastAPI routes handled them."""
from __future__ import annotations


class ValidationError(Exception):
    pass


class NotFoundError(Exception):
    pass

"""No LoginRequest/TokenResponse here — Cognito issues tokens directly (the client calls
Cognito's own SignUp/InitiateAuth APIs), so this Lambda only ever serves the profile of an
already-authenticated user."""
from __future__ import annotations

import msgspec


class UserResponse(msgspec.Struct, kw_only=True):
    id: int
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    role: str | None = None
    organization_id: int | None = None

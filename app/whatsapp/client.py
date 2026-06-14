"""Thin async wrapper over the Meta Graph API `/{phone_number_id}/messages` endpoint."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import Settings
from app.logging_setup import get_logger
from app.whatsapp.outbound_builders import (
    ListSection,
    ReplyButton,
    build_image_message,
    build_interactive_button_message,
    build_interactive_list_message,
    build_text_message,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class SendResult:
    ok: bool
    wa_message_id: str | None
    raw_response: dict[str, Any]


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return False


class WhatsAppClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self._settings = settings
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=f"{settings.whatsapp_api_base_url}/{settings.meta_phone_number_id}",
            headers={"Authorization": f"Bearer {settings.meta_whatsapp_token}"},
            timeout=20.0,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def send_text(self, to: str, body: str, preview_url: bool = False) -> SendResult:
        return await self._send(build_text_message(to, body, preview_url=preview_url))

    async def send_interactive_list(self, to: str, header: str | None, body: str,
                                    button_text: str, sections: list[ListSection]) -> SendResult:
        return await self._send(build_interactive_list_message(to, header, body, button_text, sections))

    async def send_interactive_buttons(self, to: str, body: str, buttons: list[ReplyButton],
                                       header: str | None = None) -> SendResult:
        return await self._send(build_interactive_button_message(to, body, buttons, header=header))

    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> SendResult:
        return await self._send(build_image_message(to, image_url, caption=caption))

    async def mark_as_read(self, message_id: str) -> None:
        try:
            await self._post({"messaging_product": "whatsapp", "status": "read", "message_id": message_id})
        except Exception:
            logger.warning("whatsapp_mark_as_read_failed", message_id=message_id)

    async def _send(self, body: dict[str, Any]) -> SendResult:
        try:
            response = await self._post(body)
        except Exception:
            logger.exception("whatsapp_send_failed", message_type=body.get("type"))
            return SendResult(ok=False, wa_message_id=None, raw_response={})

        wa_message_id = None
        messages = response.get("messages") or []
        if messages:
            wa_message_id = messages[0].get("id")
        return SendResult(ok=True, wa_message_id=wa_message_id, raw_response=response)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=8),
           retry=retry_if_exception(_is_retryable), reraise=True)
    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        response = await self._http.post("/messages", json=body)
        response.raise_for_status()
        return response.json()

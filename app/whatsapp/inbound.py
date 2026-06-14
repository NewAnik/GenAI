"""Parsing of Meta WhatsApp Cloud API webhook payloads into normalized inbound messages.

Meta's payload shape (trimmed):

    {"object": "whatsapp_business_account", "entry": [{"id": "...", "changes": [
        {"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": "..."},
            "contacts": [{"profile": {"name": "Jane"}, "wa_id": "9198..."}],
            "messages": [{"from": "9198...", "id": "wamid.XXX", "timestamp": "...",
                          "type": "text", "text": {"body": "Hi"}}],
            "statuses": [{"id": "wamid.XXX", "status": "delivered", ...}]
        }}
    ]}]}

`messages[].type` can be `text`, `interactive` (with `button_reply`/`list_reply`), `image`,
`location`, etc. We normalize all of these into one `WhatsAppInboundMessage` shape so the
rest of the app never has to think about Meta's JSON quirks.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MessageType = Literal["text", "interactive_button_reply", "interactive_list_reply",
                      "status_update", "unsupported"]


class WhatsAppInboundMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    whatsapp_number: str
    wa_message_id: str
    message_type: MessageType
    text: str | None = None
    interactive_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        return self.message_type in ("text", "interactive_button_reply", "interactive_list_reply")


def parse_inbound(payload: dict[str, Any]) -> list[WhatsAppInboundMessage]:
    """Flatten a (possibly multi-entry/multi-change) webhook payload into normalized messages.

    Status-update entries (`statuses`) are returned as `status_update` messages so callers
    can log-and-skip them without invoking the agent.
    """
    out: list[WhatsAppInboundMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                out.append(_normalize_message(msg))
            for status in value.get("statuses", []):
                out.append(WhatsAppInboundMessage(
                    whatsapp_number=status.get("recipient_id", ""),
                    wa_message_id=status.get("id", ""),
                    message_type="status_update",
                    raw=status,
                ))
    return out


def _normalize_message(msg: dict[str, Any]) -> WhatsAppInboundMessage:
    wa_number = msg.get("from", "")
    wa_id = msg.get("id", "")
    msg_type = msg.get("type")

    if msg_type == "text":
        return WhatsAppInboundMessage(
            whatsapp_number=wa_number, wa_message_id=wa_id, message_type="text",
            text=msg.get("text", {}).get("body"), raw=msg,
        )

    if msg_type == "interactive":
        interactive = msg.get("interactive", {})
        if "button_reply" in interactive:
            reply = interactive["button_reply"]
            return WhatsAppInboundMessage(
                whatsapp_number=wa_number, wa_message_id=wa_id,
                message_type="interactive_button_reply",
                text=reply.get("title"), interactive_id=reply.get("id"), raw=msg,
            )
        if "list_reply" in interactive:
            reply = interactive["list_reply"]
            return WhatsAppInboundMessage(
                whatsapp_number=wa_number, wa_message_id=wa_id,
                message_type="interactive_list_reply",
                text=reply.get("title"), interactive_id=reply.get("id"), raw=msg,
            )

    return WhatsAppInboundMessage(
        whatsapp_number=wa_number, wa_message_id=wa_id, message_type="unsupported", raw=msg,
    )


def decode_interactive_payload(payload_id: str) -> tuple[str, str, str | None]:
    """Splits an encoded row/button id like `gift:product:482` into (namespace, action, ref).

    Encoding scheme used by `whatsapp.outbound_builders` / `agent` nodes:
      - "gift:product:<id>"   -> a catalog product was selected
      - "gift:giftbox:<id>"   -> a gift box was selected
      - "idea:web:<index>"    -> an external/web idea row was tapped
      - "action:<name>"       -> a quick action button (more_options, refine, confirm:<id>, ...)
    """
    parts = payload_id.split(":", 2)
    if len(parts) == 3:
        namespace, action, ref = parts
        return namespace, action, ref
    if len(parts) == 2:
        namespace, action = parts
        return namespace, action, None
    return payload_id, "", None

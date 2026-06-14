"""Pure functions that build Meta Graph API `/messages` JSON bodies — no I/O, trivially
unit-testable. Kept separate from `client.py` so message *shape* and message *transport*
can be tested/changed independently.

Meta interactive-message constraints enforced here:
  - list messages: <= 10 sections, <= 10 rows total, row title <= 24 chars, description <= 72
  - reply-button messages: <= 3 buttons, button title <= 20 chars
  - images cannot be embedded in list rows — sent as separate follow-up messages by the caller
"""
from __future__ import annotations

from dataclasses import dataclass

_LIST_TITLE_MAX = 24
_LIST_DESC_MAX = 72
_BUTTON_TITLE_MAX = 20
_MAX_LIST_ROWS = 10
_MAX_BUTTONS = 3


@dataclass(frozen=True)
class ListRow:
    id: str
    title: str
    description: str | None = None


@dataclass(frozen=True)
class ListSection:
    title: str
    rows: list[ListRow]


@dataclass(frozen=True)
class ReplyButton:
    id: str
    title: str


def _truncate(text: str | None, max_len: int) -> str | None:
    if text is None:
        return None
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def build_text_message(to: str, body: str, *, preview_url: bool = False) -> dict:
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": body, "preview_url": preview_url},
    }


def build_interactive_list_message(to: str, header: str | None, body_text: str,
                                   button_text: str, sections: list[ListSection]) -> dict:
    safe_sections = []
    rows_used = 0
    for section in sections[:_MAX_LIST_ROWS]:
        rows = []
        for row in section.rows:
            if rows_used >= _MAX_LIST_ROWS:
                break
            rows.append({
                "id": row.id,
                "title": _truncate(row.title, _LIST_TITLE_MAX),
                **({"description": _truncate(row.description, _LIST_DESC_MAX)} if row.description else {}),
            })
            rows_used += 1
        if rows:
            safe_sections.append({"title": _truncate(section.title, _LIST_TITLE_MAX), "rows": rows})

    interactive: dict = {
        "type": "list",
        "body": {"text": body_text},
        "action": {"button": _truncate(button_text, _BUTTON_TITLE_MAX), "sections": safe_sections},
    }
    if header:
        interactive["header"] = {"type": "text", "text": _truncate(header, _LIST_TITLE_MAX)}

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": interactive,
    }


def build_interactive_button_message(to: str, body_text: str, buttons: list[ReplyButton],
                                     header: str | None = None) -> dict:
    interactive: dict = {
        "type": "button",
        "body": {"text": body_text},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": b.id, "title": _truncate(b.title, _BUTTON_TITLE_MAX)}}
                for b in buttons[:_MAX_BUTTONS]
            ]
        },
    }
    if header:
        interactive["header"] = {"type": "text", "text": _truncate(header, _LIST_TITLE_MAX)}

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": interactive,
    }


def build_image_message(to: str, link: str, caption: str | None = None) -> dict:
    image: dict = {"link": link}
    if caption:
        image["caption"] = caption
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "image",
        "image": image,
    }

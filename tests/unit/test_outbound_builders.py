"""Unit tests for the pure WhatsApp Graph API message-shape builders — JSON structure and the
length/count truncation rules Meta enforces on interactive messages."""
from __future__ import annotations

from app.whatsapp.outbound_builders import (
    ListRow,
    ListSection,
    ReplyButton,
    build_image_message,
    build_interactive_button_message,
    build_interactive_list_message,
    build_text_message,
)


def test_build_text_message_shape():
    msg = build_text_message("9198765", "Hello there")

    assert msg["messaging_product"] == "whatsapp"
    assert msg["to"] == "9198765"
    assert msg["type"] == "text"
    assert msg["text"] == {"body": "Hello there", "preview_url": False}


def test_build_interactive_list_message_truncates_long_titles_and_descriptions():
    long_title = "A" * 40
    long_desc = "B" * 100
    sections = [ListSection(title="From our catalog", rows=[ListRow(id="gift:product:1", title=long_title, description=long_desc)])]

    msg = build_interactive_list_message("9198765", "Header", "Body text", "View options", sections)

    row = msg["interactive"]["action"]["sections"][0]["rows"][0]
    assert len(row["title"]) <= 24
    assert row["title"].endswith("…")
    assert len(row["description"]) <= 72
    assert row["description"].endswith("…")


def test_build_interactive_list_message_caps_total_rows_at_ten():
    rows = [ListRow(id=f"gift:product:{i}", title=f"Item {i}") for i in range(15)]
    sections = [ListSection(title="From our catalog", rows=rows)]

    msg = build_interactive_list_message("9198765", None, "Body", "Choose", sections)

    total_rows = sum(len(s["rows"]) for s in msg["interactive"]["action"]["sections"])
    assert total_rows == 10


def test_build_interactive_button_message_caps_at_three_buttons():
    buttons = [ReplyButton(id=f"action:{i}", title=f"Button {i} with long text") for i in range(5)]

    msg = build_interactive_button_message("9198765", "Pick one", buttons)

    rendered = msg["interactive"]["action"]["buttons"]
    assert len(rendered) == 3
    for b in rendered:
        assert len(b["reply"]["title"]) <= 20


def test_build_image_message_includes_optional_caption():
    with_caption = build_image_message("9198765", "https://example.com/img.png", caption="Nice gift")
    without_caption = build_image_message("9198765", "https://example.com/img.png")

    assert with_caption["image"] == {"link": "https://example.com/img.png", "caption": "Nice gift"}
    assert without_caption["image"] == {"link": "https://example.com/img.png"}

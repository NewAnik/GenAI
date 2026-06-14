"""Unit tests for parsing Meta webhook payloads into normalized inbound messages, and decoding
the `gift:product:482` style interactive payload encoding scheme."""
from __future__ import annotations

from app.whatsapp.inbound import decode_interactive_payload, parse_inbound


def _payload_with_message(message: dict) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "entry-1", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": "123"},
            "contacts": [{"profile": {"name": "Jane"}, "wa_id": "919800000000"}],
            "messages": [message],
        }}]}],
    }


def test_parse_inbound_text_message():
    payload = _payload_with_message({
        "from": "919800000000", "id": "wamid.TEXT1", "timestamp": "1700000000",
        "type": "text", "text": {"body": "Hi, I need gifts for Diwali"},
    })

    messages = parse_inbound(payload)

    assert len(messages) == 1
    msg = messages[0]
    assert msg.whatsapp_number == "919800000000"
    assert msg.message_type == "text"
    assert msg.text == "Hi, I need gifts for Diwali"
    assert msg.is_actionable


def test_parse_inbound_interactive_list_reply():
    payload = _payload_with_message({
        "from": "919800000000", "id": "wamid.LIST1", "timestamp": "1700000001",
        "type": "interactive",
        "interactive": {"type": "list_reply", "list_reply": {"id": "gift:product:482", "title": "Premium Hamper"}},
    })

    messages = parse_inbound(payload)

    assert len(messages) == 1
    msg = messages[0]
    assert msg.message_type == "interactive_list_reply"
    assert msg.interactive_id == "gift:product:482"
    assert msg.text == "Premium Hamper"
    assert msg.is_actionable


def test_parse_inbound_interactive_button_reply():
    payload = _payload_with_message({
        "from": "919800000000", "id": "wamid.BTN1", "timestamp": "1700000002",
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": "action:more_options", "title": "More options"}},
    })

    messages = parse_inbound(payload)

    assert messages[0].message_type == "interactive_button_reply"
    assert messages[0].interactive_id == "action:more_options"


def test_parse_inbound_status_update_is_not_actionable():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "entry-1", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": "123"},
            "statuses": [{"id": "wamid.STATUS1", "status": "delivered", "recipient_id": "919800000000"}],
        }}]}],
    }

    messages = parse_inbound(payload)

    assert len(messages) == 1
    assert messages[0].message_type == "status_update"
    assert not messages[0].is_actionable


def test_decode_interactive_payload_three_part():
    assert decode_interactive_payload("gift:product:482") == ("gift", "product", "482")
    assert decode_interactive_payload("gift:giftbox:12") == ("gift", "giftbox", "12")
    assert decode_interactive_payload("idea:web:0") == ("idea", "web", "0")
    assert decode_interactive_payload("action:confirm:482") == ("action", "confirm", "482")


def test_decode_interactive_payload_two_part():
    assert decode_interactive_payload("action:more_options") == ("action", "more_options", None)


def test_decode_interactive_payload_malformed_falls_back():
    assert decode_interactive_payload("not_namespaced") == ("not_namespaced", "", None)

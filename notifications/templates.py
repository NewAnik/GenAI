"""Builds the order-status-change email from an SQS message payload. Deliberately plain string
templates (no template engine), same style as wrapped-and-more/functions/api/enquiry.js — this
package has no other dependency, and a handful of short emails don't need one."""
from __future__ import annotations

FROM = "Wrapped & More <orders@wrappedandmore.com>"

# Mirrors wrapped-and-more-admin/src/lib/enums.ts's orderStatus vocabulary — hand-kept in sync,
# same caveat that file already documents for its own mirrors of the DB CHECK constraint.
STATUS_LABELS = {
    "pending": "received",
    "confirmed": "confirmed",
    "in_production": "in production",
    "ready_to_ship": "ready to ship",
    "shipped": "shipped",
    "delivered": "delivered",
    "cancelled": "cancelled",
    "returned": "returned",
}


def escape_html(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def _shell(inner: str) -> str:
    return (
        '<div style="margin:0;padding:32px 24px;background:#f2e8e1">'
        '<div style="max-width:560px;margin:0 auto;padding:32px;background:#fdfaf7;'
        'border:1px solid #e4dcd4">' + inner + "</div></div>"
    )


def build_email(payload: dict) -> dict:
    """`payload` is the JSON body of one SQS record, produced by
    GenAI/storefront/services/notifications_service.py or
    GenAI/admin_api/handlers/orders_handler.py — see either for the exact shape."""
    order_number = payload.get("order_number") or f"#{payload['order_id']}"
    status_label = _status_label(payload["new_status"])
    customer_name = payload.get("customer_name") or "there"
    subject = f"Your order {order_number} is {status_label}"

    text = "\n".join(
        [
            f"Hello {customer_name},",
            "",
            f"Your order {order_number} is now {status_label}.",
            f"Order total: {payload.get('currency', 'INR')} {payload.get('total_amount', '')}",
            "",
            "You can see the full status history of this order any time on the Wrapped & More site.",
            "",
            "Wrapped & More",
        ]
    )

    html = _shell(
        f"""
        <p style="margin:0 0 4px;font:600 12px/1.4 system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#8a7f76">Order update</p>
        <h1 style="margin:0 0 20px;font:400 22px/1.3 Georgia,serif;color:#1f2a24">Your order is {escape_html(status_label)}.</h1>
        <p style="margin:0 0 16px;font:400 15px/1.6 system-ui,sans-serif;color:#2c352f">Hello {escape_html(customer_name)},</p>
        <p style="margin:0 0 24px;padding:16px 18px;background:#f7f1ea;font:400 15px/1.6 system-ui,sans-serif;color:#2c352f">
          <span style="display:block;font:600 12px/1.4 system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#8a7f76">Order</span>
          <strong style="font:400 20px/1.4 Georgia,serif;color:#1f2a24">{escape_html(order_number)}</strong>
        </p>
        <p style="margin:0;font:400 15px/1.6 system-ui,sans-serif;color:#2c352f">
          Total: {escape_html(payload.get('currency', 'INR'))} {escape_html(payload.get('total_amount', ''))}
        </p>
        """
    )

    return {
        "from": FROM,
        "to": [payload["customer_email"]],
        "subject": subject,
        "text": text,
        "html": html,
    }

"""Payment access. Payments are record-only: rows carry an external
`transaction_reference`; a signed webhook later flips their status to paid."""
from __future__ import annotations

from storefront.db.models import Payment


class PaymentRepository:
    def get_by_reference(self, transaction_reference: str) -> Payment | None:
        return (
            Payment.select()
            .where(Payment.transaction_reference == transaction_reference)
            .first()
        )

    def list_for_order(self, order_id: int) -> list[Payment]:
        return list(Payment.select().where(Payment.order_id == order_id).order_by(Payment.id))

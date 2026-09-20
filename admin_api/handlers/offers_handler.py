"""Lambda for the offer endpoints resources.yml deliberately excludes from the generic layer:
match-count (OfferDetail.tsx's useMatchCount, a read replicated here as one round trip instead of
up to 3 chained client queries) and scope attach/detach (OfferScopePicker.tsx's composite-PK
writes on offer_products/offer_categories, which have no single `id` to route the generic
create/update/delete endpoints through)."""
from __future__ import annotations

from db.connection import connection, raw_connection
from db.models.catalog import Category, Product
from db.models.offers import Offer, OfferCategory, OfferProduct
from db.repositories.user_repo import STAFF_ROLES
from handlers.common.auth import require_role
from handlers.common.errors import NotFoundError, ValidationError
from handlers.common.http import decode_json_body, json_response, path_param
from handlers.common.router import dispatch


def _get_offer(offer_id: str) -> Offer:
    offer = Offer.get_or_none(Offer.id == offer_id)
    if offer is None:
        raise NotFoundError("no offer with that id")
    return offer


def _match_count(event: dict) -> dict:
    require_role(event, *STAFF_ROLES)
    offer = _get_offer(path_param(event, "offer_id"))

    if offer.applies_to == "all":
        count = Product.select().where(Product.status == "active").count()
    elif offer.applies_to == "products":
        product_ids = [row.product for row in OfferProduct.select().where(OfferProduct.offer == offer.id)]
        count = (
            Product.select().where(Product.id.in_(product_ids), Product.status == "active").count()
            if product_ids else 0
        )
    elif offer.applies_to == "categories":
        category_ids = [row.category for row in OfferCategory.select().where(OfferCategory.offer == offer.id)]
        count = (
            Product.select().where(Product.category.in_(category_ids), Product.status == "active").count()
            if category_ids else 0
        )
    else:  # gift_boxes — every gift box qualifies, matching OfferDetail.tsx's fallback branch
        with raw_connection().cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM gift_boxes")
            count = cur.fetchone()[0]

    return json_response(200, {"count": count})


_JOIN_TABLES = {
    "products": (OfferProduct, "product", Product),
    "categories": (OfferCategory, "category", Category),
}


def _scope_list(event: dict) -> dict:
    """Backs OfferScopePicker.tsx's `attached` list — offer_products/offer_categories are
    composite-PK tables excluded from the generic `/resources/{table}/...` family (see
    resources.yml's header comment), so this bespoke read replaces what used to be a
    useRelatedRows call against them directly."""
    require_role(event, *STAFF_ROLES)
    offer = _get_offer(path_param(event, "offer_id"))
    body = decode_json_body(event)
    kind = body.get("kind")
    if kind not in _JOIN_TABLES:
        raise ValidationError("body must include kind ('products'|'categories')")

    model, field_name, target_model = _JOIN_TABLES[kind]
    rows = []
    for join_row in model.select().where(model.offer == offer.id):
        target_id = getattr(join_row, field_name)
        target = target_model.get_or_none(target_model.id == target_id)
        rows.append({
            "offer_id": offer.id,
            field_name + "_id": target_id,
            kind[:-1]: {"id": target_id, "name": target.name if target else None,
                        **({"status": target.status} if kind == "products" and target else {})},
        })
    return json_response(200, {"rows": rows})


def _scope_attach(event: dict) -> dict:
    require_role(event, *STAFF_ROLES)
    offer = _get_offer(path_param(event, "offer_id"))
    body = decode_json_body(event)
    kind = body.get("kind")
    target_id = body.get("targetId")
    if kind not in _JOIN_TABLES or not target_id:
        raise ValidationError("body must include kind ('products'|'categories') and targetId")

    model, field_name, target_model = _JOIN_TABLES[kind]
    if target_model.get_or_none(target_model.id == target_id) is None:
        raise ValidationError(f"no {kind[:-1]} with that id")

    model.insert(offer=offer.id, **{field_name: target_id}).on_conflict_ignore().execute()
    return json_response(200, {"ok": True})


def _scope_detach(event: dict) -> dict:
    require_role(event, *STAFF_ROLES)
    offer = _get_offer(path_param(event, "offer_id"))
    body = decode_json_body(event)
    kind = body.get("kind")
    target_id = body.get("targetId")
    if kind not in _JOIN_TABLES or not target_id:
        raise ValidationError("body must include kind ('products'|'categories') and targetId")

    model, field_name, _ = _JOIN_TABLES[kind]
    field = getattr(model, field_name)
    model.delete().where(model.offer == offer.id, field == target_id).execute()
    return json_response(200, {"ok": True})


ROUTES = {
    "POST /offers/{offer_id}/match-count": _match_count,
    "POST /offers/{offer_id}/scope/list": _scope_list,
    "POST /offers/{offer_id}/scope/attach": _scope_attach,
    "POST /offers/{offer_id}/scope/detach": _scope_detach,
}


def lambda_handler(event: dict, context=None) -> dict:
    with connection():
        return dispatch(event, ROUTES)

"""Resolving a stored catalog-image object key into a full CDN URL — shared by catalog_handler.py
and cart_handler.py, both of which render gift-box images."""
from __future__ import annotations

from config import get_settings


def resolve_catalog_image_url(object_key: str | None) -> str | None:
    if not object_key:
        return None
    domain = get_settings().catalog_images_cdn_domain
    if not domain:
        return None
    return f"https://{domain}/{object_key}"

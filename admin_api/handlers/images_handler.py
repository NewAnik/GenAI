"""Lambda for POST /images/presign-upload and POST /images/delete — replaces
wrapped-and-more-admin/src/lib/storage.ts's Supabase Storage calls. The client-side resize/
validate step (canvas downscale to 2000px, WebP re-encode) stays exactly as it is today; this
endpoint only ever mints a presigned S3 PUT URL or deletes an object, and — this is the point —
always generates the object key itself from validated `prefix`/`ownerId` inputs rather than
trusting a client-supplied key, closing off path traversal / overwrite-arbitrary-object risk."""
from __future__ import annotations

import os
import re
import uuid

import boto3
from config import get_settings
from db.connection import connection
from db.repositories.user_repo import STAFF_ROLES
from handlers.common.auth import require_role
from handlers.common.errors import ValidationError
from handlers.common.http import decode_json_body, json_response
from handlers.common.router import dispatch

_ALLOWED_PREFIXES = ("products", "gift-boxes")
_ALLOWED_CONTENT_TYPES = ("image/jpeg", "image/png", "image/webp", "image/avif")
_KEY_PATTERN = re.compile(r"^(products|gift-boxes)/\d+/[0-9a-f-]{36}\.webp$")

# A plain `boto3.client("s3")` signs correctly for this region (Lambda's AWS_REGION env var) but
# still builds the URL against the global `s3.amazonaws.com` virtual-hosted host, which S3 answers
# with a 307 redirect to the bucket's actual regional endpoint for a bucket outside us-east-1 (or
# one whose global-DNS routing hasn't caught up yet right after creation). A redirect response
# carries no CORS headers, so the browser blocks the presigned PUT outright before ever following
# it — pinning `endpoint_url` to the regional host makes the first request already correct, so
# there is nothing to redirect.
_REGION = os.environ.get("AWS_REGION", "ap-south-1")
_s3 = boto3.client("s3", region_name=_REGION, endpoint_url=f"https://s3.{_REGION}.amazonaws.com")


def _presign_upload(event: dict) -> dict:
    require_role(event, *STAFF_ROLES)
    body = decode_json_body(event)
    prefix = body.get("prefix")
    owner_id = body.get("ownerId")
    content_type = body.get("contentType", "image/webp")

    if prefix not in _ALLOWED_PREFIXES:
        raise ValidationError(f"prefix must be one of {_ALLOWED_PREFIXES}")
    if not isinstance(owner_id, int) or owner_id <= 0:
        raise ValidationError("ownerId must be a positive integer")
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise ValidationError(f"contentType must be one of {_ALLOWED_CONTENT_TYPES}")

    object_key = f"{prefix}/{owner_id}/{uuid.uuid4()}.webp"
    bucket = get_settings().catalog_images_bucket
    upload_url = _s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": object_key, "ContentType": "image/webp"},
        ExpiresIn=300,
    )
    return json_response(200, {"uploadUrl": upload_url, "objectKey": object_key})


def _delete(event: dict) -> dict:
    require_role(event, *STAFF_ROLES)
    body = decode_json_body(event)
    object_key = body.get("objectKey")
    if not object_key or not _KEY_PATTERN.match(object_key):
        raise ValidationError("objectKey is missing or does not match the expected pattern")

    bucket = get_settings().catalog_images_bucket
    _s3.delete_object(Bucket=bucket, Key=object_key)
    return json_response(200, {"ok": True})


ROUTES = {
    "POST /images/presign-upload": _presign_upload,
    "POST /images/delete": _delete,
}


def lambda_handler(event: dict, context=None) -> dict:
    # require_role's staff-profile lookup needs Postgres, same as every other handler here —
    # despite this Lambda's real work (S3) not otherwise touching the database.
    with connection():
        return dispatch(event, ROUTES, context)

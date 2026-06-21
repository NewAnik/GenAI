"""Meta WhatsApp Cloud API webhook: the GET verification handshake (run once when you register
the callback URL in the Meta App Dashboard) and the POST inbound-message receiver.

Inbound handling returns 200 immediately and processes messages in a background task — Meta
expects a fast ack and will retry aggressively (with growing backoff, eventually disabling the
endpoint) if the webhook is slow or errors, so the actual LLM/DB/send work must happen off the
request path.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
import traceback2 as tb
from app.api.deps import get_orchestrator, get_settings_dep
from app.config import Settings
from app.logging_setup import get_logger
from app.services.conversation_orchestrator import ConversationOrchestrator
from app.whatsapp.inbound import WhatsAppInboundMessage, parse_inbound
from app.whatsapp.signature import verify_signature

logger = get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.get("")
async def verify_webhook(request: Request, settings: Settings = Depends(get_settings_dep)) -> Response:
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")
    logger.info(mode)
    logger.info(token)
    logger.info(challenge)
    logger.info(settings.meta_verify_token)

    if mode == "subscribe" and token == settings.meta_verify_token and settings.meta_verify_token:
        logger.info("webhook_verification_succeeded")
        return Response(content=challenge, media_type="text/plain", status_code=status.HTTP_200_OK)

    logger.warning("webhook_verification_failed", mode=mode)
    return Response(status_code=status.HTTP_403_FORBIDDEN)


@router.post("")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks,
                          settings: Settings = Depends(get_settings_dep),
                          orchestrator: ConversationOrchestrator = Depends(get_orchestrator)) -> Response:
    raw_body = await request.body()
    signature_header = request.headers.get("X-Hub-Signature-256")

    if settings.meta_app_secret and not verify_signature(raw_body, signature_header, settings.meta_app_secret):
        logger.warning("webhook_signature_verification_failed")
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("webhook_payload_not_json")
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    messages = parse_inbound(payload)
    logger.info("webhook_payload_received", message_count=len(messages))

    for message in messages:
        background_tasks.add_task(_handle_safely, orchestrator, message)

    # Always 200 — Meta only cares that we acknowledged receipt.
    return Response(status_code=status.HTTP_200_OK)


async def _handle_safely(orchestrator: ConversationOrchestrator, message: WhatsAppInboundMessage) -> None:
    try:
        await orchestrator.handle_inbound(message)
    except Exception:
        tb.print_exc()
        logger.exception("inbound_message_handling_failed", wa_message_id=message.wa_message_id)

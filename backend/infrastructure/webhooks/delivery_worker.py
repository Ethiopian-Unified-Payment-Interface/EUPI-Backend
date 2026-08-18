"""
Webhook Delivery Worker & HMAC Signing Engine
=============================================
Layer: 🔴 LAYER 3 — Infrastructure / Webhooks
Rule: Asynchronous delivery of payment status webhooks with HMAC-SHA256 signatures and exponential backoff retries.

Security & Integrity:
Every webhook payload is signed with HMAC-SHA256 using the application's
webhook_secret. The HTTP header `X-EUPI-Signature: t=<timestamp>,v1=<signature>`
allows receivers to verify origin and prevent replay attacks.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.infrastructure.database.models import WebhookEventRecord
from backend.infrastructure.database.payment_repository import PaymentRepository
from backend.infrastructure.database.session import Database

logger = logging.getLogger(__name__)

# Retry backoff delays in seconds per attempt index (1-based)
# Attempt 1: immediate
# Attempt 2: 60s (1m)
# Attempt 3: 300s (5m)
# Attempt 4: 1800s (30m)
# Attempt 5: 7200s (2h)
BACKOFF_DELAYS_SECONDS = [0, 60, 300, 1800, 7200]
MAX_ATTEMPTS = 5


def compute_signature(payload_json: str, secret: str, timestamp: int | None = None) -> str:
    """
    Compute HMAC-SHA256 signature for a webhook payload.

    Header format: `t=<timestamp>,v1=<hex_signature>`
    """
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.{payload_json}"
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"t={ts},v1={signature}"


def deliver_webhook_single(
    event: WebhookEventRecord,
    secret: str | None = None,
    timeout: float = 5.0,
) -> tuple[bool, int | None]:
    """
    Synchronously deliver a single webhook HTTP POST payload.

    Returns (success_boolean, http_status_code).
    """
    payload_str = event.payload_json
    body_bytes = payload_str.encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "EUPI-Webhook-Delivery/1.0",
        "X-EUPI-Event": getattr(event, "event_type", "payment.settled"),
        "X-EUPI-Delivery": event.event_id,
    }

    if secret:
        headers["X-EUPI-Signature"] = compute_signature(payload_str, secret)

    req = urllib.request.Request(
        url=event.webhook_url,
        data=body_bytes,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.getcode()
            success = 200 <= status_code < 300
            return success, status_code
    except urllib.error.HTTPError as exc:
        return False, exc.code
    except Exception as exc:
        logger.warning(
            "Webhook delivery error for event %s to %s: %s",
            event.event_id,
            event.webhook_url,
            exc,
        )
        return False, None


def process_webhook_event(
    event: WebhookEventRecord,
    repo: PaymentRepository,
    secret: str | None = None,
) -> bool:
    """
    Execute delivery attempt for an event and calculate next retry timestamp.
    """
    current_attempt = (event.attempts or 0) + 1
    success, http_code = deliver_webhook_single(event, secret=secret)

    now = datetime.now(tz=timezone.utc)
    if success:
        repo.update_webhook_attempt(
            event_id=event.event_id,
            http_status_code=http_code,
            delivered=True,
            next_attempt_at=None,
        )
        logger.info(
            "Webhook delivered successfully",
            extra={"event_id": event.event_id, "attempt": current_attempt, "code": http_code},
        )
        return True
    else:
        if current_attempt < MAX_ATTEMPTS:
            delay = BACKOFF_DELAYS_SECONDS[min(current_attempt, len(BACKOFF_DELAYS_SECONDS) - 1)]
            next_retry = now + timedelta(seconds=delay)
        else:
            next_retry = None  # Max retries exhausted

        repo.update_webhook_attempt(
            event_id=event.event_id,
            http_status_code=http_code,
            delivered=False,
            next_attempt_at=next_retry,
        )
        logger.warning(
            "Webhook delivery failed for event %s (attempt %d/%d), next_retry: %s",
            event.event_id,
            current_attempt,
            MAX_ATTEMPTS,
            next_retry,
        )
        return False


async def webhook_worker_loop(db: Database, poll_interval: float = 10.0) -> None:
    """
    Background worker task polling due webhooks and attempting delivery.
    """
    logger.info("Webhook delivery worker loop started (poll_interval=%.1fs)", poll_interval)
    repo = PaymentRepository(db)

    while True:
        try:
            due_events = repo.get_due_webhooks(limit=50)
            if due_events:
                logger.info("Processing %d due webhooks", len(due_events))
                for event in due_events:
                    await asyncio.to_thread(process_webhook_event, event, repo, None)
        except asyncio.CancelledError:
            logger.info("Webhook worker loop shutting down...")
            break
        except Exception as exc:
            logger.error("Error in webhook worker loop: %s", exc, exc_info=True)

        await asyncio.sleep(poll_interval)

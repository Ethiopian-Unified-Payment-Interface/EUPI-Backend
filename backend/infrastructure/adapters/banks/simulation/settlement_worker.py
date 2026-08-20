"""
Simulated Bank Settlement Worker
================================
Layer: 🔴 LAYER 3 — Infrastructure / Driven Adapters

The bank's own settlement dispatcher, simulated.

This is the piece that did not exist. A real rail accepts a debit order, works
its books, and then calls back to confirm — and EUPI has always had the endpoint
to receive that call. Nothing ever made it. Every payment therefore reached
ORDERED and stopped there permanently, which the Super App renders as a pending
transfer that never clears.

This worker plays the bank. It polls transfers the simulator has posted, waits
out the configured settlement delay, and confirms or rejects them through the
same application-layer path the HTTP callback uses. It is deliberately *not* a
shortcut inside the payment flow: settlement is asynchronous at a real bank, and
a sandbox that settles synchronously hides every bug that only exists while a
payment is in flight.

Multiple application workers may run this loop. Orders are claimed with
`SKIP LOCKED` where the database supports it, so two of them cannot confirm the
same transfer.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

from backend.application.use_cases.payment_settlement_service import (
    PaymentNotFoundError,
    PaymentSettlementService,
)
from backend.infrastructure.adapters.banks.simulation.engine import (
    DueOrder,
    SimulatedCoreBankingEngine,
)

logger = logging.getLogger(__name__)

# Give up notifying EUPI about one order after this many passes, rather than
# retrying a permanently broken payment forever and drowning the log. The order
# stays POSTED and visibly stuck, which is the correct outcome: a settlement
# that cannot be recorded is an operations problem, not something to discard.
MAX_NOTIFY_ATTEMPTS = 10

_REJECTION_REASON = "Simulated bank rejected the transfer at settlement."


def rejects(end_to_end_id: str, failure_rate: float) -> bool:
    """
    Whether the simulated bank rejects this transfer.

    Derived from the reference rather than sampled fresh, so a retry reaches
    the same verdict. A worker that re-decided on every pass could reverse a
    transfer it had already confirmed.

    Args:
        end_to_end_id: The transfer's reference.
        failure_rate:  Share of transfers to reject, 0 to 1.

    Returns:
        True when this transfer should be rejected.
    """
    if failure_rate <= 0:
        return False
    if failure_rate >= 1:
        return True

    digest = hashlib.blake2b(end_to_end_id.encode("utf-8"), digest_size=4).digest()
    position = int.from_bytes(digest, "big") / 0xFFFFFFFF
    return position < failure_rate


def process_due_order(
    order: DueOrder,
    engine: SimulatedCoreBankingEngine,
    settlement: PaymentSettlementService,
    failure_rate: float,
) -> None:
    """
    Confirm or reject one posted transfer.

    EUPI is notified *before* the bank's order row is finalised. That ordering
    is what makes a crash recoverable: the order stays POSTED, the next pass
    claims it again, and notifying twice is a no-op because settlement is
    idempotent. Finalising first would leave a transfer the bank considers done
    and EUPI considers still in flight, with nothing left to retry it.

    Args:
        order:        The claimed transfer.
        engine:       The simulated core banking system.
        settlement:   Application-layer settlement.
        failure_rate: Share of transfers the bank rejects.
    """
    rejected = rejects(order.end_to_end_id, failure_rate)

    try:
        settlement.settle_by_reference(
            end_to_end_id=order.end_to_end_id,
            bank_confirmed=not rejected,
            bank_order_reference=order.order_reference,
            failure_reason=_REJECTION_REASON if rejected else None,
        )
    except PaymentNotFoundError:
        # The simulator moved money for a transfer EUPI has no record of. That
        # is not a retryable condition, and leaving the funds moved would be
        # worse than backing them out.
        logger.error(
            "Simulated transfer has no matching payment; reversing it.",
            extra={"end_to_end_id": order.end_to_end_id},
        )
        engine.reverse(order.end_to_end_id, "No matching EUPI payment.")
        return
    except Exception:  # noqa: BLE001
        if order.attempts >= MAX_NOTIFY_ATTEMPTS:
            logger.error(
                "Giving up notifying EUPI of settlement after %d attempts. The "
                "order remains POSTED and needs operator attention.",
                order.attempts,
                extra={"end_to_end_id": order.end_to_end_id},
            )
            return
        logger.exception(
            "Could not notify EUPI of settlement; will retry.",
            extra={
                "end_to_end_id": order.end_to_end_id,
                "attempt": order.attempts,
            },
        )
        return

    if rejected:
        engine.reverse(order.end_to_end_id, _REJECTION_REASON)
    else:
        engine.mark_settled(order.end_to_end_id)


async def settlement_worker_loop(
    engine: SimulatedCoreBankingEngine,
    settlement: PaymentSettlementService,
    poll_interval: float = 2.0,
    failure_rate: float = 0.0,
    batch_size: int = 25,
) -> None:
    """
    Poll for transfers whose settlement is due and confirm them.

    Args:
        engine:        The simulated core banking system.
        settlement:    Application-layer settlement.
        poll_interval: Seconds between passes.
        failure_rate:  Share of transfers the bank rejects, 0 to 1.
        batch_size:    Maximum orders handled per pass.
    """
    logger.info(
        "Simulated bank settlement worker started "
        "(poll_interval=%.1fs, failure_rate=%.2f)",
        poll_interval,
        failure_rate,
    )

    while True:
        try:
            due = await asyncio.to_thread(engine.claim_due_orders, batch_size)
            for order in due:
                await asyncio.to_thread(
                    process_due_order, order, engine, settlement, failure_rate
                )
        except asyncio.CancelledError:
            logger.info("Simulated bank settlement worker shutting down.")
            break
        except Exception:  # noqa: BLE001
            logger.exception("Simulated bank settlement pass failed; continuing.")

        try:
            await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info("Simulated bank settlement worker shutting down.")
            break

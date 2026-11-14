"""Glue between EBICS downloads and pretix's bundled banktransfer plugin."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.cache import cache

from . import ebics

if TYPE_CHECKING:
    from .models import EBICSConnection

logger = logging.getLogger(__name__)

# On the first run there is no watermark, so look this far back.
INITIAL_BACKFILL_DAYS = 90
# Re-request a few days before the last watermark; banktransfer deduplicates via
# its checksum/external_id, so overlapping a previous run is safe.
OVERLAP_DAYS = 5
# How long a connection may not start a second banktransfer job after the first.
JOB_LOCK_SECONDS = 300


@dataclass
class ImportResult:
    num_transactions: int
    job_id: int | None = None
    num_refunds: int = 0


def _squash(text: str) -> str:
    """Reduce a reference to letters and digits: banks break and re-space it anywhere."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def confirm_refunds(conn: EBICSConnection, outgoing: list[dict[str, Any]], since: date) -> int:
    """Mark open refunds as done once their outgoing transfer shows up on a statement.

    Outgoing transfers are never handed to banktransfer: it would store every one of
    them (rent, salaries) for admins to see, and it refuses the usual case, a refund
    for a canceled order. A transfer only counts when all of this holds, and every
    other one is dropped here:

    - its reference names an order of this organizer,
    - that order has an open manual or bank transfer refund of exactly that amount,
    - it was booked on or after the day the refund was created (an older transfer
      paid for an earlier refund),
    - it has not confirmed a refund before (``since`` is the start of the fetched
      range, which overlaps the previous one).
    """
    from pretix.base.models import OrderRefund

    refunds = OrderRefund.objects.filter(
        order__event__organizer=conn.organizer,
        order__event__currency=conn.currency,
        provider__in=("manual", "banktransfer"),
    ).select_related("order__event")
    pending = list(
        refunds.filter(
            state__in=(OrderRefund.REFUND_STATE_CREATED, OrderRefund.REFUND_STATE_TRANSIT)
        )
    )
    if not outgoing or not pending:
        return 0

    used = {
        refund.info_data.get("statement_id")
        for refund in refunds.filter(
            state=OrderRefund.REFUND_STATE_DONE,
            execution_date__date__gte=since - timedelta(days=1),
        )
    }
    confirmed = 0
    for row in outgoing:
        statement_id = "|".join(
            (row["external_id"] or "", row["date"], row["amount"], row["reference"])
        )
        if statement_id in used:
            continue
        reference = _squash(row["reference"])
        for refund in pending:
            created = refund.created.astimezone(refund.order.event.timezone).date()
            if (
                refund.amount == -Decimal(row["amount"])
                and _squash(refund.order.full_code) in reference
                and created.isoformat() <= row["date"]  # ISO dates sort as text
            ):
                # Stored the way banktransfer's own import stores a matched transfer.
                refund.provider = "banktransfer"
                refund.info_data = {
                    **refund.info_data,
                    **{key: row[key] for key in ("reference", "date", "payer", "iban", "bic")},
                    "statement_id": statement_id,
                }
                refund.done()
                pending.remove(refund)
                used.add(statement_id)
                confirmed += 1
                break
    return confirmed


def import_for_connection(conn: EBICSConnection) -> ImportResult | None:
    """Download new statements for ``conn`` and hand them to banktransfer.

    Creates an organizer-scoped ``BankImportJob`` and dispatches the banktransfer
    ``process_banktransfers`` task, which matches order codes and confirms
    payments. The connection's import watermark is advanced to today. Outgoing
    transfers only confirm open refunds (see ``confirm_refunds``).

    Returns ``None``, without importing, when a job for this connection was started
    moments ago.
    """
    from pretix.plugins.banktransfer.models import BankImportJob
    from pretix.plugins.banktransfer.tasks import process_banktransfers

    end = date.today()
    if conn.last_imported_date:
        start = conn.last_imported_date - timedelta(days=OVERLAP_DAYS)
    else:
        start = end - timedelta(days=INITIAL_BACKFILL_DAYS)

    transactions = ebics.fetch_statements(conn, start, end)
    incoming = [row for row in transactions if not row["amount"].startswith("-")]
    outgoing = [row for row in transactions if row["amount"].startswith("-")]

    job_id: int | None = None
    if incoming:
        # banktransfer looks for duplicates in memory, so two jobs running at once with the
        # same rows (a double click, or a click during the hourly run) import them twice.
        # shortcut: no lock on pretix's dummy cache (no Redis/memcached), use a database
        # lock if such an instance ever shows duplicate transactions.
        if not cache.add(f"pretix_ebics_job_{conn.pk}", "1", JOB_LOCK_SECONDS):
            return None
        job = BankImportJob.objects.create(organizer=conn.organizer, currency=conn.currency)
        process_banktransfers.apply_async(kwargs={"job": job.pk, "data": incoming})
        job_id = job.pk

    # Only after the hand-over: if that fails, the next run must fetch the range again.
    conn.last_imported_date = end
    conn.save(update_fields=["last_imported_date", "keyring_data"])

    # After the hand-over, so that a problem here never holds back payments.
    num_refunds = confirm_refunds(conn, outgoing, start)

    logger.info(
        "EBICS import for %s: %d incoming transfer(s) between %s and %s (job %s), "
        "%d refund(s) confirmed",
        conn,
        len(incoming),
        start,
        end,
        job_id,
        num_refunds,
    )
    return ImportResult(num_transactions=len(incoming), job_id=job_id, num_refunds=num_refunds)

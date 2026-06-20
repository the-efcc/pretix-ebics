"""Glue between EBICS downloads and pretix's bundled banktransfer plugin."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from . import ebics

if TYPE_CHECKING:
    from .models import EBICSConnection

logger = logging.getLogger(__name__)

# On the first run there is no watermark, so look this far back.
INITIAL_BACKFILL_DAYS = 90
# Re-request a few days before the last watermark; banktransfer deduplicates via
# its checksum/external_id, so overlapping a previous run is safe.
OVERLAP_DAYS = 5


@dataclass
class ImportResult:
    connection: str
    start: date
    end: date
    num_transactions: int
    job_id: int | None = None


def import_for_connection(conn: EBICSConnection) -> ImportResult:
    """Download new statements for ``conn`` and hand them to banktransfer.

    Creates an organizer-scoped ``BankImportJob`` and dispatches the banktransfer
    ``process_banktransfers`` task, which matches order codes and confirms
    payments. The connection's import watermark is advanced to today.
    """
    from pretix.plugins.banktransfer.models import BankImportJob
    from pretix.plugins.banktransfer.tasks import process_banktransfers

    end = date.today()
    if conn.last_imported_date:
        start = conn.last_imported_date - timedelta(days=OVERLAP_DAYS)
    else:
        start = end - timedelta(days=INITIAL_BACKFILL_DAYS)

    transactions = ebics.fetch_statements(conn, start, end)

    conn.last_imported_date = end
    conn.save(update_fields=["last_imported_date", "keyring_data"])

    job_id: int | None = None
    if transactions:
        job = BankImportJob.objects.create(organizer=conn.organizer, currency=conn.currency)
        process_banktransfers.apply_async(kwargs={"job": job.pk, "data": transactions})
        job_id = job.pk

    logger.info(
        "EBICS import for %s: %d transaction(s) between %s and %s (job %s)",
        conn,
        len(transactions),
        start,
        end,
        job_id,
    )
    return ImportResult(
        connection=str(conn),
        start=start,
        end=end,
        num_transactions=len(transactions),
        job_id=job_id,
    )

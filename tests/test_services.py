from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from pretix.plugins.banktransfer.models import BankImportJob
from pretix.plugins.banktransfer.tasks import process_banktransfers

from pretix_ebics import services
from pretix_ebics.models import EBICSConnection

pytestmark = pytest.mark.django_db


@pytest.fixture
def connection(organizer):
    return EBICSConnection.objects.create(
        organizer=organizer,
        name="Test Bank",
        host_id="HOST",
        partner_id="P1",
        user_id="U1",
        ebics_url="https://ebics.example.com/ebics",
        currency="EUR",
        bank_keys_activated=True,
    )


@pytest.fixture
def no_dispatch(monkeypatch):
    """Record process_banktransfers dispatch without actually running matching."""
    mock = MagicMock()
    monkeypatch.setattr(process_banktransfers, "apply_async", mock)
    return mock


def _row(ref="Order ABC12", amount="23.00", ext="R1"):
    return {
        "payer": "John Doe",
        "reference": ref,
        "amount": amount,
        "date": "2026-01-15",
        "iban": "DE89370400440532013000",
        "bic": "COBADEFFXXX",
        "external_id": ext,
    }


def test_import_creates_job_and_dispatches(monkeypatch, connection, no_dispatch):
    rows = [_row(ext="R1"), _row(ref="Order ZZ999", ext="R2")]
    monkeypatch.setattr(services.ebics, "fetch_statements", lambda conn, start, end: rows)

    result = services.import_for_connection(connection)

    assert result.num_transactions == 2
    assert result.job_id is not None
    job = BankImportJob.objects.get(pk=result.job_id)
    assert job.organizer == connection.organizer
    assert job.currency == "EUR"
    no_dispatch.assert_called_once_with(kwargs={"job": job.pk, "data": rows})

    connection.refresh_from_db()
    assert connection.last_imported_date == date.today()


def test_first_run_backfills(monkeypatch, connection, no_dispatch):
    captured = {}

    def fake_fetch(conn, start, end):
        captured["start"], captured["end"] = start, end
        return []

    monkeypatch.setattr(services.ebics, "fetch_statements", fake_fetch)

    result = services.import_for_connection(connection)

    assert captured["end"] == date.today()
    assert captured["start"] == date.today() - timedelta(days=services.INITIAL_BACKFILL_DAYS)
    assert result.num_transactions == 0
    assert result.job_id is None
    assert not BankImportJob.objects.exists()
    no_dispatch.assert_not_called()


def test_subsequent_run_overlaps_watermark(monkeypatch, connection, no_dispatch):
    connection.last_imported_date = date(2026, 1, 10)
    connection.save()
    captured = {}

    def fake_fetch(conn, start, end):
        captured["start"] = start
        return []

    monkeypatch.setattr(services.ebics, "fetch_statements", fake_fetch)

    services.import_for_connection(connection)

    assert captured["start"] == date(2026, 1, 10) - timedelta(days=services.OVERLAP_DAYS)

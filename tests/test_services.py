from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from pretix.base.models import OrderRefund, Organizer
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


def test_skips_when_a_job_was_just_started(monkeypatch, connection, no_dispatch):
    monkeypatch.setattr(services.ebics, "fetch_statements", lambda conn, start, end: [_row()])
    monkeypatch.setattr(services.cache, "add", lambda *a, **k: False)

    assert services.import_for_connection(connection) is None

    assert not BankImportJob.objects.exists()
    no_dispatch.assert_not_called()
    connection.refresh_from_db()
    assert connection.last_imported_date is None


def test_failed_hand_over_keeps_the_watermark(monkeypatch, connection, no_dispatch):
    monkeypatch.setattr(services.ebics, "fetch_statements", lambda conn, start, end: [_row()])
    no_dispatch.side_effect = RuntimeError("broker down")

    with pytest.raises(RuntimeError):
        services.import_for_connection(connection)

    connection.refresh_from_db()
    assert connection.last_imported_date is None


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


TODAY = date.today().isoformat()


def _refund(order, amount="23.00", **kwargs):
    return order.refunds.create(
        provider="manual",
        state=OrderRefund.REFUND_STATE_CREATED,
        source=OrderRefund.REFUND_SOURCE_ADMIN,
        amount=Decimal(amount),
        **kwargs,
    )


def _debit(reference="Refund DEMO-ABC12", amount="-23.00", booked=TODAY, ext="D1"):
    return {**_row(ref=reference, amount=amount, ext=ext), "payer": "Jane Doe", "date": booked}


def _import(monkeypatch, connection, rows):
    monkeypatch.setattr(services.ebics, "fetch_statements", lambda conn, start, end: rows)
    return services.import_for_connection(connection)


def test_outgoing_transfer_confirms_its_refund_and_nothing_else_is_kept(
    monkeypatch, connection, no_dispatch, order
):
    refund = _refund(order)
    credit, rent = _row(), _debit(reference="Rent January", amount="-900.00", ext="D2")

    result = _import(monkeypatch, connection, [credit, _debit(), rent])

    assert result.num_refunds == 1
    refund.refresh_from_db()
    assert refund.state == OrderRefund.REFUND_STATE_DONE
    assert refund.info_data["reference"] == "Refund DEMO-ABC12"
    # Outgoing transfers never reach banktransfer, which would store them all.
    assert no_dispatch.call_args.kwargs["kwargs"]["data"] == [credit]
    assert result.num_transactions == 1


@pytest.mark.parametrize(
    "debit",
    [
        _debit(amount="-22.00"),  # not the refund's amount
        _debit(reference="Refund for your ticket"),  # no order code
        _debit(reference="Refund DEMO-ZZZ99"),  # another order
        # Booked before the refund existed: it paid for an earlier refund.
        _debit(booked=(date.today() - timedelta(days=1)).isoformat()),
    ],
)
def test_outgoing_transfer_that_is_no_match_changes_nothing(
    monkeypatch, connection, no_dispatch, order, debit
):
    refund = _refund(order)

    assert _import(monkeypatch, connection, [debit]).num_refunds == 0

    refund.refresh_from_db()
    assert refund.state == OrderRefund.REFUND_STATE_CREATED
    no_dispatch.assert_not_called()


def test_reference_broken_up_by_the_bank_still_matches(monkeypatch, connection, no_dispatch, order):
    refund = _refund(order)

    _import(monkeypatch, connection, [_debit(reference="refund demo abc 12 thanks")])

    refund.refresh_from_db()
    assert refund.state == OrderRefund.REFUND_STATE_DONE


def test_one_transfer_confirms_one_refund_even_when_fetched_again(
    monkeypatch, connection, no_dispatch, order
):
    """Statements overlap between runs: the same transfer must not confirm a second refund."""
    first, second = _refund(order), _refund(order)

    assert _import(monkeypatch, connection, [_debit()]).num_refunds == 1
    assert _import(monkeypatch, connection, [_debit()]).num_refunds == 0

    first.refresh_from_db()
    second.refresh_from_db()
    assert sorted([first.state, second.state]) == sorted(
        [OrderRefund.REFUND_STATE_DONE, OrderRefund.REFUND_STATE_CREATED]
    )


def test_refunds_of_another_organizer_are_left_alone(monkeypatch, connection, no_dispatch, order):
    refund = _refund(order)
    other = Organizer.objects.create(name="Other", slug="other", plugins="pretix_ebics")
    connection.organizer = other
    connection.save()

    assert _import(monkeypatch, connection, [_debit()]).num_refunds == 0

    refund.refresh_from_db()
    assert refund.state == OrderRefund.REFUND_STATE_CREATED

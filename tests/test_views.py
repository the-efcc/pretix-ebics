from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse
from pretix.base.models import Team, User

from pretix_ebics import views
from pretix_ebics.models import EBICSConnection

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(organizer):
    user = User.objects.create_user("admin@example.com", "password")
    team = Team.objects.create(
        organizer=organizer,
        name="Admins",
        all_organizer_permissions=True,
        all_event_permissions=True,
        all_events=True,
    )
    team.members.add(user)
    return user


@pytest.fixture
def limited_member(organizer):
    """A member of the organizer who lacks organizer-settings permission."""
    user = User.objects.create_user("limited@example.com", "password")
    team = Team.objects.create(
        organizer=organizer,
        name="Viewers",
        all_organizer_permissions=False,
        all_event_permissions=True,
        all_events=True,
    )
    team.members.add(user)
    return user


@pytest.fixture
def client_admin(admin):
    c = Client()
    c.force_login(admin)
    return c


@pytest.fixture
def connection(organizer):
    return EBICSConnection.objects.create(
        organizer=organizer,
        name="My Bank",
        host_id="HOST",
        partner_id="P1",
        user_id="U1",
        ebics_url="https://ebics.example.com/ebics",
        bank_keys_activated=True,
    )


def _url(name, organizer, **extra):
    return reverse(f"plugins:pretix_ebics:{name}", kwargs={"organizer": organizer.slug, **extra})


def test_list_requires_permission(organizer, limited_member):
    c = Client()
    c.force_login(limited_member)
    assert c.get(_url("list", organizer)).status_code == 403


def test_pages_are_gone_when_the_plugin_is_disabled(client_admin, organizer, connection):
    organizer.plugins = ""
    organizer.save()
    assert client_admin.get(_url("list", organizer)).status_code == 404
    assert client_admin.get(_url("iniletter", organizer, pk=connection.pk)).status_code == 404


def test_list_shows_connections(client_admin, organizer, connection):
    resp = client_admin.get(_url("list", organizer))
    assert resp.status_code == 200
    assert b"My Bank" in resp.content


def test_list_flags_a_connection_whose_imports_fail(client_admin, organizer, connection):
    connection.last_imported_date = date.today() - timedelta(days=3)
    connection.save()
    resp = client_admin.get(_url("list", organizer))
    assert b"imports are failing" in resp.content
    assert b'aria-label="Delete"' in resp.content


def test_create_connection(client_admin, organizer):
    resp = client_admin.post(
        _url("add", organizer),
        {
            "name": "New Bank",
            "bank_name": "",
            "host_id": "H",
            "partner_id": "P",
            "user_id": "U",
            "ebics_url": "https://ebics.example.com/ebics",
            "ebics_version": "H004",
            "currency": "EUR",
            "passphrase": "correct horse",
            "active": "on",
        },
    )
    assert resp.status_code == 302
    conn = EBICSConnection.objects.get(name="New Bank")
    assert conn.organizer == organizer


def test_action_create_keys_saves_the_connection(monkeypatch, client_admin, organizer, connection):
    def fake_create_keys(conn):
        conn.keyring_data, conn.keys_created = "{}", True

    monkeypatch.setattr(views.ebics, "create_keys", fake_create_keys)
    resp = client_admin.post(
        _url("action", organizer, pk=connection.pk), {"action": "create_keys"}, follow=True
    )
    assert b"EBICS keys have been generated." in resp.content
    connection.refresh_from_db()
    assert connection.keys_created is True
    assert connection.keyring_data == "{}"


def test_action_failure_is_reported(monkeypatch, client_admin, organizer, connection):
    monkeypatch.setattr(views.ebics, "create_keys", MagicMock(side_effect=RuntimeError("boom")))
    resp = client_admin.post(
        _url("action", organizer, pk=connection.pk), {"action": "create_keys"}, follow=True
    )
    assert b"The operation failed: boom" in resp.content
    connection.refresh_from_db()
    assert connection.keys_created is False


def test_action_import_now(monkeypatch, client_admin, organizer, connection):
    result = MagicMock(num_transactions=3, num_refunds=0)
    mock = MagicMock(return_value=result)
    monkeypatch.setattr(views, "import_for_connection", mock)
    resp = client_admin.post(
        _url("action", organizer, pk=connection.pk), {"action": "import_now"}, follow=True
    )
    assert b"Fetched 3 transaction(s) from the bank." in resp.content
    mock.assert_called_once()


def test_action_import_now_refused_for_an_inactive_connection(
    monkeypatch, client_admin, organizer, connection
):
    connection.active = False
    connection.save()
    mock = MagicMock()
    monkeypatch.setattr(views, "import_for_connection", mock)
    resp = client_admin.post(
        _url("action", organizer, pk=connection.pk), {"action": "import_now"}, follow=True
    )
    assert b"Unknown action." in resp.content
    mock.assert_not_called()


def test_action_import_now_reports_confirmed_refunds(
    monkeypatch, client_admin, organizer, connection, order
):
    """The real import service inside a request: pretix scopes its queries there."""
    refund = order.refunds.create(provider="manual", state="created", source="admin", amount=23)
    debit = {
        "payer": "Jane Doe",
        "reference": "Refund DEMO-ABC12",
        "amount": "-23.00",
        "date": date.today().isoformat(),
        "iban": "",
        "bic": "",
        "external_id": "D1",
    }
    monkeypatch.setattr(views.ebics, "fetch_statements", lambda conn, start, end: [debit])
    resp = client_admin.post(
        _url("action", organizer, pk=connection.pk), {"action": "import_now"}, follow=True
    )
    assert b"1 refund(s) were marked as done." in resp.content
    refund.refresh_from_db()
    assert refund.state == "done"


def test_action_import_now_while_a_job_is_running(monkeypatch, client_admin, organizer, connection):
    monkeypatch.setattr(views, "import_for_connection", lambda conn: None)
    resp = client_admin.post(
        _url("action", organizer, pk=connection.pk), {"action": "import_now"}, follow=True
    )
    assert b"was started a moment ago" in resp.content


def test_ini_letter_inline_by_default(monkeypatch, client_admin, admin, organizer, connection):
    admin.locale = "de-informal"
    admin.save()
    mock = MagicMock(return_value=b"%PDF-1.4")
    monkeypatch.setattr(views.ebics, "ini_letter_pdf", mock)
    resp = client_admin.get(_url("iniletter", organizer, pk=connection.pk))
    assert mock.call_args.kwargs == {"lang": "de"}
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    assert resp["Content-Disposition"].startswith("inline")
    assert resp.content == b"%PDF-1.4"


def test_ini_letter_forced_download(monkeypatch, client_admin, organizer, connection):
    monkeypatch.setattr(views.ebics, "ini_letter_pdf", lambda conn, lang: b"%PDF-1.4")
    resp = client_admin.get(_url("iniletter", organizer, pk=connection.pk) + "?download=1")
    assert resp["Content-Disposition"].startswith("attachment")

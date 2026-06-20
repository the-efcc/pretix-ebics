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


def test_list_shows_connections(client_admin, organizer, connection):
    resp = client_admin.get(_url("list", organizer))
    assert resp.status_code == 200
    assert b"My Bank" in resp.content


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
            "passphrase": "secret",
            "active": "on",
        },
    )
    assert resp.status_code == 302
    conn = EBICSConnection.objects.get(name="New Bank")
    assert conn.organizer == organizer


def test_action_create_keys(monkeypatch, client_admin, organizer, connection):
    called = MagicMock()
    monkeypatch.setattr(views.ebics, "create_keys", called)
    resp = client_admin.post(_url("action", organizer, pk=connection.pk), {"action": "create_keys"})
    assert resp.status_code == 302
    called.assert_called_once()


def test_action_import_now(monkeypatch, client_admin, organizer, connection):
    result = MagicMock(num_transactions=3)
    mock = MagicMock(return_value=result)
    monkeypatch.setattr(views, "import_for_connection", mock)
    resp = client_admin.post(_url("action", organizer, pk=connection.pk), {"action": "import_now"})
    assert resp.status_code == 302
    mock.assert_called_once()


def test_ini_letter_inline_by_default(monkeypatch, client_admin, organizer, connection):
    monkeypatch.setattr(views.ebics, "ini_letter_pdf", lambda conn: b"%PDF-1.4")
    resp = client_admin.get(_url("iniletter", organizer, pk=connection.pk))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    assert resp["Content-Disposition"].startswith("inline")
    assert resp.content == b"%PDF-1.4"


def test_ini_letter_forced_download(monkeypatch, client_admin, organizer, connection):
    monkeypatch.setattr(views.ebics, "ini_letter_pdf", lambda conn: b"%PDF-1.4")
    resp = client_admin.get(_url("iniletter", organizer, pk=connection.pk) + "?download=1")
    assert resp["Content-Disposition"].startswith("attachment")

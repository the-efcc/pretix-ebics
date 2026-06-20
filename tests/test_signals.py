from unittest.mock import MagicMock

import pytest

from pretix_ebics import signals
from pretix_ebics.models import EBICSConnection

pytestmark = pytest.mark.django_db


def _make_connection(organizer, name, *, active=True, activated=True):
    return EBICSConnection.objects.create(
        organizer=organizer,
        name=name,
        host_id="HOST",
        partner_id="P1",
        user_id="U1",
        ebics_url="https://ebics.example.com/ebics",
        active=active,
        bank_keys_activated=activated,
    )


@pytest.fixture
def unthrottled(monkeypatch):
    """Pretend the throttle lock is free so the receiver runs."""
    monkeypatch.setattr(signals.cache, "add", lambda *a, **k: True)


def test_imports_only_ready_connections(monkeypatch, organizer, unthrottled):
    ready = _make_connection(organizer, "ready")
    _make_connection(organizer, "inactive", active=False)
    _make_connection(organizer, "not-activated", activated=False)

    imported = []
    monkeypatch.setattr(signals, "import_for_connection", lambda conn: imported.append(conn.pk))

    signals.run_ebics_imports(sender=None)

    assert imported == [ready.pk]


def test_throttle_skips_run(monkeypatch, organizer):
    _make_connection(organizer, "ready")
    monkeypatch.setattr(signals.cache, "add", lambda *a, **k: False)
    called = MagicMock()
    monkeypatch.setattr(signals, "import_for_connection", called)

    signals.run_ebics_imports(sender=None)

    called.assert_not_called()


def test_failure_does_not_stop_other_connections(monkeypatch, organizer, unthrottled):
    a = _make_connection(organizer, "a")
    b = _make_connection(organizer, "b")

    seen = []

    def flaky(conn):
        seen.append(conn.pk)
        if conn.pk == a.pk:
            raise RuntimeError("boom")

    monkeypatch.setattr(signals, "import_for_connection", flaky)

    signals.run_ebics_imports(sender=None)

    assert set(seen) == {a.pk, b.pk}

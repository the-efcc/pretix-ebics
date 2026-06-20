import pytest

from pretix_ebics.models import EBICSConnection

pytestmark = pytest.mark.django_db


@pytest.fixture
def connection(organizer):
    return EBICSConnection.objects.create(
        organizer=organizer,
        name="Test Bank",
        bank_name="Test Bank AG",
        host_id="EBIXHOST",
        partner_id="PARTNER1",
        user_id="USER1",
        ebics_url="https://ebics.example.com/ebics",
    )


def test_defaults(connection):
    assert connection.ebics_version == EBICSConnection.EBICS_VERSION_H004
    assert connection.currency == "EUR"
    assert connection.active is True
    assert connection.keys_created is False
    assert connection.last_imported_date is None


def test_str(connection):
    assert str(connection) == "Test Bank (dummy)"


def test_keys_sent_requires_both_transfers(connection):
    assert connection.keys_sent is False
    connection.ini_sent = True
    assert connection.keys_sent is False
    connection.hia_sent = True
    assert connection.keys_sent is True


def test_is_ready(connection):
    assert connection.is_ready is False
    connection.bank_keys_activated = True
    assert connection.is_ready is True
    connection.active = False
    assert connection.is_ready is False


def test_scoped_to_organizer(connection, organizer):
    assert list(EBICSConnection.objects.filter(organizer=organizer)) == [connection]

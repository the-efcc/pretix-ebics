import pytest

from pretix_ebics.forms import EBICSConnectionForm
from pretix_ebics.models import EBICSConnection

DATA = {
    "name": "Bank",
    "bank_name": "",
    "host_id": "H",
    "partner_id": "P",
    "user_id": "U",
    "ebics_url": "https://ebics.example.com/ebics",
    "ebics_version": "H004",
    "currency": "EUR",
    "passphrase": "correct horse",
    "active": "on",
}


def test_valid_data():
    assert EBICSConnectionForm(DATA).is_valid()


@pytest.mark.parametrize(
    "field,value",
    [
        ("passphrase", ""),  # fintech: "passphrase required to store private key"
        ("passphrase", "secret"),  # fintech: "must be at least 8 characters long"
        ("ebics_url", "http://ebics.example.com/ebics"),
        ("currency", "eur"),  # banktransfer compares it exactly with the event currency
    ],
)
def test_rejects_values_that_break_the_connection(field, value):
    form = EBICSConnectionForm({**DATA, field: value})
    assert field in form.errors


def test_passphrase_is_locked_once_keys_exist():
    conn = EBICSConnection(passphrase="correct horse", keys_created=True)
    form = EBICSConnectionForm({**DATA, "passphrase": "another passphrase"}, instance=conn)

    assert form.is_valid()
    assert form.cleaned_data["passphrase"] == "correct horse"
    assert "correct horse" not in form.as_p()

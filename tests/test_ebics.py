from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pretix_ebics import ebics


def make_txn(amount, *, purpose=("Order ABC12",), name="John Doe", eref=None,
             iban="DE89370400440532013000", bic="COBADEFFXXX", bank_reference="REF1"):
    return SimpleNamespace(
        amount=SimpleNamespace(value=Decimal(str(amount)), currency="EUR"),
        purpose=purpose,
        name=name,
        eref=eref,
        date=date(2026, 1, 15),
        iban=iban,
        bic=bic,
        bank_reference=bank_reference,
    )


def test_transaction_to_dict_basic():
    d = ebics._transaction_to_dict(make_txn("23.00"))
    assert d == {
        "payer": "John Doe",
        "reference": "Order ABC12",
        "amount": "23.00",
        "date": "2026-01-15",
        "iban": "DE89370400440532013000",
        "bic": "COBADEFFXXX",
        "external_id": "REF1",
    }


def test_transaction_to_dict_appends_eref():
    d = ebics._transaction_to_dict(make_txn("5.00", purpose=("foo",), eref="ORDER99"))
    assert d["reference"] == "foo ORDER99"


def test_transaction_to_dict_hashes_external_id_when_missing():
    d = ebics._transaction_to_dict(make_txn("5.00", bank_reference=None))
    assert d["external_id"].startswith("ebics-")


def _patch_session(monkeypatch, session):
    @contextmanager
    def fake_cm(conn):
        yield session

    monkeypatch.setattr(ebics, "ebics_session", fake_cm)


def test_fetch_statements_keeps_only_credits(monkeypatch):
    session = SimpleNamespace(client=MagicMock())
    session.client.C53.return_value = {"stmt": "<xml/>"}
    credit = make_txn("10.00", bank_reference="C1")
    debit = make_txn("-7.00", bank_reference="D1")
    monkeypatch.setattr(ebics, "CAMTDocument", lambda xml: [credit, debit])
    _patch_session(monkeypatch, session)

    result = ebics.fetch_statements(SimpleNamespace(), date(2026, 1, 1), date(2026, 1, 31))

    assert [r["external_id"] for r in result] == ["C1"]
    session.client.C53.assert_called_once_with(start=date(2026, 1, 1), end=date(2026, 1, 31))
    session.client.confirm_download.assert_called_once()


@pytest.mark.parametrize(
    "func,method,flag",
    [
        (ebics.send_ini, "INI", "ini_sent"),
        (ebics.send_hia, "HIA", "hia_sent"),
    ],
)
def test_key_transfers_set_flags(monkeypatch, func, method, flag):
    session = SimpleNamespace(client=MagicMock(), user=MagicMock(), bank=MagicMock())
    _patch_session(monkeypatch, session)
    conn = SimpleNamespace(ini_sent=False, hia_sent=False)

    func(conn)

    getattr(session.client, method).assert_called_once()
    assert getattr(conn, flag) is True


def test_create_keys(monkeypatch):
    session = SimpleNamespace(client=MagicMock(), user=MagicMock(), bank=MagicMock())
    _patch_session(monkeypatch, session)
    conn = SimpleNamespace(keys_created=False)

    ebics.create_keys(conn)

    session.user.create_keys.assert_called_once_with(keyversion=ebics.KEY_VERSION)
    assert conn.keys_created is True


def test_activate_bank_keys(monkeypatch):
    session = SimpleNamespace(client=MagicMock(), user=MagicMock(), bank=MagicMock())
    _patch_session(monkeypatch, session)
    conn = SimpleNamespace(bank_keys_activated=False)

    ebics.activate_bank_keys(conn)

    session.client.HPB.assert_called_once()
    session.bank.activate_keys.assert_called_once()
    assert conn.bank_keys_activated is True


def test_ini_letter_pdf(monkeypatch):
    session = SimpleNamespace(client=MagicMock(), user=MagicMock(), bank=MagicMock())
    session.user.create_ini_letter.return_value = b"%PDF-1.4"
    _patch_session(monkeypatch, session)
    conn = SimpleNamespace(bank_name="Demo Bank", host_id="HOST")

    pdf = ebics.ini_letter_pdf(conn, lang="en")

    assert pdf == b"%PDF-1.4"
    session.user.create_ini_letter.assert_called_once_with(bankname="Demo Bank", lang="en")

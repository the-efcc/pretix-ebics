import os
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
        batch=False,
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


def test_transaction_to_dict_ignores_placeholder_eref():
    d = ebics._transaction_to_dict(make_txn("5.00", purpose=("foo",), eref="NOTPROVIDED"))
    assert d["reference"] == "foo"


def test_transaction_to_dict_without_bank_reference():
    d = ebics._transaction_to_dict(make_txn("5.00", bank_reference=None))
    assert d["external_id"] is None


def test_key_lifecycle_with_real_fintech():
    """No mocks: keys are generated offline, stored on the connection and reopened."""
    conn = SimpleNamespace(
        keyring_data="",
        passphrase="correct horse",
        host_id="HOST",
        ebics_url="https://ebics.example.com/ebics",
        partner_id="P1",
        user_id="U1",
        ebics_version="H004",
        bank_name="Demo Bank",
        keys_created=False,
    )

    ebics.create_keys(conn)

    assert conn.keys_created is True
    assert conn.keyring_data
    assert ebics.ini_letter_pdf(conn, lang="en").startswith(b"%PDF")


def test_rejected_license_falls_back_to_evaluation_mode(monkeypatch):
    monkeypatch.setenv("FINTECH_LICENSE_KEYCODE", "typo")
    calls = []

    def fake_register():
        calls.append(os.environ.get("FINTECH_LICENSE_KEYCODE"))
        if calls[-1]:
            raise RuntimeError("invalid keycode")

    monkeypatch.setattr(ebics.fintech, "register", fake_register)

    ebics._register()

    assert calls == ["typo", None]


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


def test_fetch_statements_without_data(monkeypatch):
    session = SimpleNamespace(client=MagicMock())
    session.client.C53.return_value = None  # fintech's answer when nothing is available
    _patch_session(monkeypatch, session)

    assert ebics.fetch_statements(SimpleNamespace(), date(2026, 1, 1), date(2026, 1, 31)) == []
    assert session.client.suppress_no_data_error is True
    session.client.confirm_download.assert_not_called()


# One credit of 23.00 and one batch of two 23.00 credits that share a bank reference.
CAMT_WITH_BATCH = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt>
<GrpHdr><MsgId>M1</MsgId><CreDtTm>2026-01-16T06:00:00</CreDtTm></GrpHdr>
<Stmt><Id>S1</Id><ElctrncSeqNb>1</ElctrncSeqNb><CreDtTm>2026-01-16T06:00:00</CreDtTm>
<Acct><Id><IBAN>DE02120300000000202051</IBAN></Id><Ccy>EUR</Ccy></Acct>
<Ntry><Amt Ccy="EUR">23.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts>BOOK</Sts>
 <BookgDt><Dt>2026-01-15</Dt></BookgDt><AcctSvcrRef>SINGLE</AcctSvcrRef>
 <NtryDtls><TxDtls><Refs><EndToEndId>NOTPROVIDED</EndToEndId></Refs>
  <RltdPties><Dbtr><Nm>John</Nm></Dbtr></RltdPties>
  <RmtInf><Ustrd>DEMO-AB</Ustrd><Ustrd>C12</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="EUR">46.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts>BOOK</Sts>
 <BookgDt><Dt>2026-01-15</Dt></BookgDt><AcctSvcrRef>BATCH</AcctSvcrRef>
 <NtryDtls><Btch><NbOfTxs>2</NbOfTxs></Btch>
  <TxDtls><Refs><EndToEndId>E1</EndToEndId></Refs>
   <AmtDtls><TxAmt><Amt Ccy="EUR">23.00</Amt></TxAmt></AmtDtls>
   <RltdPties><Dbtr><Nm>Alice</Nm></Dbtr></RltdPties><RmtInf><Ustrd>DEMO-AAAAA</Ustrd></RmtInf></TxDtls>
  <TxDtls><Refs><EndToEndId>E2</EndToEndId></Refs>
   <AmtDtls><TxAmt><Amt Ccy="EUR">23.00</Amt></TxAmt></AmtDtls>
   <RltdPties><Dbtr><Nm>Bob</Nm></Dbtr></RltdPties><RmtInf><Ustrd>DEMO-BBBBB</Ustrd></RmtInf></TxDtls>
 </NtryDtls></Ntry>
</Stmt></BkToCstmrStmt></Document>"""


def test_fetch_statements_parses_real_camt_and_opens_batches(monkeypatch):
    """The real fintech parser: a batch must yield its transfers, not one empty row."""
    session = SimpleNamespace(client=MagicMock())
    session.client.C53.return_value = {"stmt": CAMT_WITH_BATCH}
    _patch_session(monkeypatch, session)

    rows = ebics.fetch_statements(SimpleNamespace(), date(2026, 1, 1), date(2026, 1, 31))

    assert [(r["payer"], r["reference"], r["amount"], r["external_id"]) for r in rows] == [
        ("John", "DEMO-AB C12", "23.00", "SINGLE"),
        ("Alice", "DEMO-AAAAA E1", "23.00", None),
        ("Bob", "DEMO-BBBBB E2", "23.00", None),
    ]


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

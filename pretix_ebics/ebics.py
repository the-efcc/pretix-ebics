"""Thin wrapper around the joonis ``fintech`` library.

Everything that talks to the bank over EBICS lives here: the keyring lifecycle,
the key-exchange steps (INI/HIA/HPB), the INI-letter PDF, and downloading and
parsing camt.053 account statements into plain dicts that pretix's banktransfer
plugin understands.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any

import fintech
from django.conf import settings


def _register() -> None:
    """Register the fintech license, falling back to evaluation mode.

    fintech refuses to import its EBICS submodule until ``register()`` has been
    called, so this runs at import time. A configured license (Django settings or
    the matching environment variables) lifts the evaluation-mode restrictions:
    without it, SEPA uploads are capped and statements from the last three days
    cannot be retrieved.
    """
    name = getattr(settings, "FINTECH_LICENSE_NAME", None) or os.environ.get(
        "FINTECH_LICENSE_NAME"
    )
    keycode = getattr(settings, "FINTECH_LICENSE_KEYCODE", None) or os.environ.get(
        "FINTECH_LICENSE_KEYCODE"
    )
    if name and keycode:
        users = getattr(settings, "FINTECH_LICENSE_USERS", None) or os.environ.get(
            "FINTECH_LICENSE_USERS"
        )
        kwargs: dict[str, Any] = {"name": name, "keycode": keycode}
        if users:
            kwargs["users"] = tuple(u.strip() for u in str(users).split(",") if u.strip())
        fintech.register(**kwargs)
    else:
        fintech.register()


_register()

from fintech.ebics import EbicsBank, EbicsClient, EbicsKeyRing, EbicsUser  # noqa: E402
from fintech.sepa import CAMTDocument  # noqa: E402

if TYPE_CHECKING:
    from .models import EBICSConnection

# Signature key version. A006 (RSASSA-PSS) is recommended for both H004 and H005.
KEY_VERSION = "A006"


@dataclass
class EbicsSession:
    bank: EbicsBank
    user: EbicsUser
    version: str

    @cached_property
    def client(self) -> EbicsClient:
        # Built on first use: fintech refuses to create a client before the user has keys.
        return EbicsClient(self.bank, self.user, version=self.version)


@contextmanager
def ebics_session(conn: EBICSConnection) -> Iterator[EbicsSession]:
    """Build a fintech client for ``conn`` backed by a temporary keyring file.

    The keyring is materialized from ``conn.keyring_data`` into a temp file for the
    duration of the call, then written back into ``conn.keyring_data`` so that any
    key material created during the session is persisted by the caller (the caller
    is responsible for ``conn.save()``).
    """
    with TemporaryDirectory() as tmp:
        keypath = os.path.join(tmp, "keyring.ebics")
        if conn.keyring_data:
            with open(keypath, "w") as fh:
                fh.write(conn.keyring_data)

        keyring = EbicsKeyRing(keys=keypath, passphrase=conn.passphrase or None)
        yield EbicsSession(
            bank=EbicsBank(keyring, conn.host_id, conn.ebics_url),
            user=EbicsUser(keyring, conn.partner_id, conn.user_id),
            version=conn.ebics_version,
        )

        keyring.save()
        with open(keypath) as fh:
            conn.keyring_data = fh.read()


def create_keys(conn: EBICSConnection) -> None:
    """Generate the user's EBICS keys (signature, authentication, encryption)."""
    with ebics_session(conn) as session:
        session.user.create_keys(keyversion=KEY_VERSION)
    conn.keys_created = True


def send_ini(conn: EBICSConnection) -> None:
    """Transmit the public signature key to the bank (INI order)."""
    with ebics_session(conn) as session:
        session.client.INI()
    conn.ini_sent = True


def send_hia(conn: EBICSConnection) -> None:
    """Transmit the public authentication and encryption keys (HIA order)."""
    with ebics_session(conn) as session:
        session.client.HIA()
    conn.hia_sent = True


def activate_bank_keys(conn: EBICSConnection) -> None:
    """Download the bank's public keys (HPB) and activate them in the keyring."""
    with ebics_session(conn) as session:
        session.client.HPB()
        session.bank.activate_keys()
    conn.bank_keys_activated = True


def ini_letter_pdf(conn: EBICSConnection, lang: str | None = None) -> bytes:
    """Return the INI letter as PDF bytes, to be printed, signed and mailed."""
    with ebics_session(conn) as session:
        return session.user.create_ini_letter(bankname=conn.bank_name or conn.host_id, lang=lang)


def _transaction_to_dict(txn: Any) -> dict[str, Any]:
    parts = [str(p) for p in (txn.purpose or ()) if p]
    eref = getattr(txn, "eref", None)
    # Banks fill an empty end-to-end reference with the word NOTPROVIDED.
    if eref and str(eref) != "NOTPROVIDED" and str(eref) not in parts:
        parts.append(str(eref))
    reference = " ".join(parts)

    booking = txn.date
    date_str = booking.isoformat() if hasattr(booking, "isoformat") else str(booking)

    return {
        "payer": txn.name or "",
        "reference": reference,
        "amount": str(txn.amount.value),
        "date": date_str,
        "iban": getattr(txn, "iban", "") or "",
        "bic": getattr(txn, "bic", "") or "",
        # Without it banktransfer detects duplicates by payer, reference, amount and date.
        "external_id": txn.bank_reference or None,
    }


def fetch_statements(conn: EBICSConnection, start: date, end: date) -> list[dict[str, Any]]:
    """Download camt.053 statements for ``[start, end]`` and return credit transfers.

    Only incoming (credit) transactions are returned, mapped to the field names the
    banktransfer plugin expects. The download is confirmed so the bank does not
    serve the same statements again on the next run.
    """
    results: list[dict[str, Any]] = []
    with ebics_session(conn) as session:
        # A date range without statements is normal, not an error.
        session.client.suppress_no_data_error = True
        documents = session.client.C53(start=start, end=end)
        if not documents:
            return results
        for xml in documents.values():
            for entry in CAMTDocument(xml):
                # A batch entry is one booking that holds the real transfers; it has none
                # inside when the bank delivers them in a separate file.
                transfers = list(entry) if entry.batch else []
                for txn in transfers or [entry]:
                    if txn.amount.value > 0:
                        row = _transaction_to_dict(txn)
                        if transfers:
                            # They share the batch's bank reference, which banktransfer
                            # would take for the same transfer imported twice.
                            row["external_id"] = None
                        results.append(row)
        session.client.confirm_download()
    return results

# pretix-ebics

Automatically import bank transfers over [EBICS](https://en.wikipedia.org/wiki/EBICS)
into pretix.

This plugin connects to any bank that speaks the EBICS standard, downloads account
statements (camt.053) using the [joonis `fintech`](https://www.joonis.de/en/fintech/)
library, and feeds the incoming transfers into pretix's bundled **bank transfer**
plugin so that orders are matched and marked as paid automatically.

## How it works

The plugin is an **organizer-level integration**, not a payment provider:

1. You configure one *EBICS connection* per organizer (bank endpoint + credentials)
   and perform the one-time key exchange with the bank.
2. A periodic task (and an "Import now" button) downloads new camt.053 statements,
   keeps the incoming (credit) transfers, and creates an organizer-wide
   `BankImportJob`.
3. pretix's built-in bank transfer plugin matches the payment references against
   your order codes and confirms the matching payments.
4. Outgoing transfers are not imported. The plugin only uses them to tick off refunds
   you wired by hand: when a transfer's reference contains an order code and its
   amount equals an open manual or bank transfer refund of that order, the refund is
   marked as done. The transfer must be booked on or after the day the refund was
   created. Every other outgoing transfer is discarded and never stored.

## Requirements

- pretix >= 2026.3.0 with the built-in **Bank transfer** plugin enabled.
- An EBICS-enabled bank account and EBICS access credentials (host/partner/user IDs
  and the bank's EBICS URL).
- The `fintech` package (installed automatically as a dependency).

## Installation

### PyPI

```bash
pip install pretix-ebics
```

### NixOS

```nix
{ inputs, pkgs, ... }:
{
  services.pretix = {
    enable = true;
    plugins = [
      inputs.pretix-ebics.packages.${pkgs.stdenv.hostPlatform.system}.default
    ];
  };
}
```

## fintech license

`fintech` is "Free To Use But Restricted". In **evaluation mode** (no license) the
EBICS module cannot retrieve statements from the **last three days** and caps SEPA
uploads. For production, obtain a license from joonis and set it in the environment
of the pretix processes (web, worker and cron). Entries in `pretix.cfg` are not read:

```
FINTECH_LICENSE_NAME=<your licensee name>
FINTECH_LICENSE_KEYCODE=<your key code>
# optional, comma-separated, if your license is bound to specific EBICS user IDs
FINTECH_LICENSE_USERS=USER1,USER2
```

The license is registered once, when pretix starts. If fintech rejects it, the error
is logged and the plugin runs in evaluation mode, so check the log after changing it.

## Setup walkthrough

EBICS is a *restricted* plugin, because a connection makes the server send requests to
a URL typed in by an organizer admin. A system administrator first has to allow it: in
admin mode, open the organizer's settings and select EBICS under **Allow usage of
restricted plugins**. Then enable the plugin for the organizer, open
**Organizer → EBICS** in the control panel and:

1. **Add a connection** with the bank's Host ID, your Partner ID and User ID, the
   EBICS URL (`https://` only), the EBICS version (H004 = EBICS 2.5, H005 = EBICS 3.0),
   the account currency, and a passphrase of at least 8 characters that will encrypt
   the private keys. The passphrase cannot be changed once the keys exist.
2. **Generate keys** to create your EBICS key set (and, for EBICS 3.0, the self-signed
   certificates that carry it).
3. **Send INI** and **Send HIA** to transmit your public keys to the bank.
4. **Open the INI letter** (it opens inline in a new tab; append `?download=1` to
   save it). It shows the SHA-256 hashes of your keys. Depending on the bank you
   either sign and mail/upload it, or simply copy the hash values into the bank's
   EBICS portal — that out-of-band check is what activates your keys, however the
   bank chooses to receive it.
5. Once the bank has activated your user, click **Activate bank keys** to fetch and
   trust the bank's public keys (HPB). The connection is now *ready*.
6. From then on the periodic task imports new statements automatically; you can also
   click **Import now** at any time. A connection that has not imported for more than
   two days is labelled **imports are failing**; the reason is in the pretix log.

Disabling the plugin for an organizer stops its imports and hides its pages. The
connections and their keys are kept.

## Security

EBICS credentials and the key material are stored in the pretix database (the trust
boundary). Private keys inside the keyring are encrypted with the per-connection
passphrase, but that passphrase is stored in the same database row. The encryption
therefore does not protect the keys from anyone who can read the database or one of
its backups.

Ask your bank for an EBICS user that may only download statements. A leaked key can
then be used to read your statements, but not to send payments.

Deleting a connection discards its keys and requires repeating the key exchange with
the bank.

## Development

### Setup with uv

```bash
uv venv
uv pip install -e ".[dev]"
```

### Setup with Nix

```bash
nix develop   # or: direnv allow
```

### Running checks

```bash
uv run ruff check .
uv run ty check pretix_ebics/
uv run pytest tests/ --cov=pretix_ebics --cov-report=term-missing -v
```

The test suite mocks everything that would call the bank, and the bank transfer task,
so it needs neither network access nor a fintech license. Key storage and statement
parsing run against the real `fintech` library.

## License

GNU Affero General Public License v3.0 (AGPLv3)

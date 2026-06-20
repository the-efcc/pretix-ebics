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
uploads. For production, obtain a license from joonis and configure it through your
pretix settings or environment:

```
FINTECH_LICENSE_NAME=<your licensee name>
FINTECH_LICENSE_KEYCODE=<your key code>
# optional, comma-separated, if your license is bound to specific EBICS user IDs
FINTECH_LICENSE_USERS=USER1,USER2
```

The license is registered once at import time.

## Setup walkthrough

The plugin must be enabled for your organizer. Then open
**Organizer → EBICS** in the control panel and:

1. **Add a connection** with the bank's Host ID, your Partner ID and User ID, the
   EBICS URL, the EBICS version (H004 = EBICS 2.5, H005 = EBICS 3.0), the account
   currency, and a passphrase that will encrypt the private keys.
2. **Generate keys** to create your EBICS key set.
3. **Send INI** and **Send HIA** to transmit your public keys to the bank.
4. **Open the INI letter** (it opens inline in a new tab; append `?download=1` to
   save it). It shows the SHA-256 hashes of your keys. Depending on the bank you
   either sign and mail/upload it, or simply copy the hash values into the bank's
   EBICS portal — that out-of-band check is what activates your keys, however the
   bank chooses to receive it.
5. Once the bank has activated your user, click **Activate bank keys** to fetch and
   trust the bank's public keys (HPB). The connection is now *ready*.
6. From then on the periodic task imports new statements automatically; you can also
   click **Import now** at any time.

## Security

EBICS credentials and the key material are stored in the pretix database (the trust
boundary). Private keys inside the keyring are encrypted with the per-connection
passphrase. Deleting a connection discards its keys and requires repeating the key
exchange with the bank.

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

The test suite mocks `fintech` and the bank transfer task, so it needs neither
network access nor a fintech license.

## License

GNU Affero General Public License v3.0 (AGPLv3)

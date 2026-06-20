# Development Guide

This document helps AI agents understand the pretix-ebics project structure and
development workflow.

## Project Overview

EBICS bank-transfer import plugin for pretix. It is **not** a payment provider: it is
an organizer-level integration that periodically downloads bank statements over EBICS
and imports the incoming transfers, reusing pretix's bundled `banktransfer` plugin for
order matching and payment confirmation.

## Key Files

- **`pretix_ebics/models.py`**: `EBICSConnection` model (one EBICS connection per organizer).
- **`pretix_ebics/ebics.py`**: `fintech` wrapper — keyring lifecycle, key exchange
  (INI/HIA/HPB), INI-letter PDF, and statement download + camt.053 parsing.
- **`pretix_ebics/services.py`**: import orchestration — builds a `BankImportJob` and
  calls the banktransfer `process_banktransfers` task.
- **`pretix_ebics/signals.py`**: periodic import task + organizer nav entry.
- **`pretix_ebics/views.py`** / **`urls.py`**: organizer control panel views.
- **`tests/`**: pytest test suite (fintech and banktransfer are mocked).

## Architecture

### Import flow
1. `periodic_task` (signals) fires on an interval, iterates active `EBICSConnection`s.
2. `services.import_for_connection()` downloads camt.053 via `ebics.fetch_statements()`.
3. Credit transactions are mapped to banktransfer fields
   (`payer`, `reference`, `amount`, `date`, `iban`, `bic`, `external_id`).
4. An organizer-scoped `BankImportJob` is created and `process_banktransfers(job, data)`
   is invoked; banktransfer matches order codes and confirms payments.

### Key-exchange flow (manual, admin-driven)
1. Admin creates an `EBICSConnection` and generates keys (`create_keys`).
2. `send_ini` / `send_hia` transmit the public keys to the bank.
3. Admin downloads the INI letter (PDF), signs it, and mails it to the bank.
4. Once the bank activates the user, `activate_bank_keys` (HPB) fetches the bank keys.

## Development Commands
```bash
# Lint
devenv shell -- uv run ruff check --fix

# Type check
devenv shell -- uv run ty check pretix_ebics/

# Test
devenv shell -- uv run pytest tests/ -q -W ignore --cov=pretix_ebics --cov-report=term-missing
```

## Important Conventions

1. **Scope**: organizer-level. Connections and `BankImportJob`s are organizer-scoped.
2. **Type Hints**: use `PretixHttpRequest` for views that access `request.organizer`.
3. **Secrets**: EBICS keyring JSON is passphrase-encrypted and stored in the DB on the
   `EBICSConnection`. The pretix database is the trust boundary.
4. **Import Sorting**: stdlib -> third-party -> local (enforced by ruff).

## Testing Strategy

- Unit tests for the camt parser and the import service.
- `fintech.ebics` / `fintech.sepa` are fully mocked (no network, no license required).
- The banktransfer `process_banktransfers` task is mocked in import-service tests.
- Coverage reporting in CI with a diff comment on PRs.

## CI/CD

GitHub workflow runs on PRs:
- **test**: pytest with coverage (Python 3.11-3.14)
- **coverage-diff**: shows coverage change in PR comments
- **typecheck**: ty type checking
- **lint**: ruff linting

## Type System Notes

- Ignore unresolved imports/attributes for `fintech.*` (no type stubs) in
  `pretix_ebics/ebics.py` via the `[tool.ty.overrides]` block in `pyproject.toml`.
- Django plugin configured with `DJANGO_SETTINGS_MODULE = "tests.settings"`.
- `tests/settings.py` installs both `pretix_ebics` and `pretix.plugins.banktransfer`.

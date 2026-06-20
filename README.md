# pretix-ebics

Automatically import bank transfers over [EBICS](https://en.wikipedia.org/wiki/EBICS)
into pretix.

This plugin connects to any bank that speaks the EBICS standard, downloads account
statements (camt.053) using the [joonis `fintech`](https://www.joonis.de/en/fintech/)
library, and feeds the incoming transfers into pretix's bundled **bank transfer**
plugin so that orders are matched and marked as paid automatically.

> [!NOTE]
> This is an early-stage plugin. The full setup walkthrough and configuration
> reference are added as the corresponding features land.

## Requirements

- pretix >= 2026.3.0 with the built-in **Bank transfer** plugin enabled.
- An EBICS-enabled bank account and EBICS access credentials (host/partner/user IDs).
- The `fintech` package. It is "Free To Use But Restricted": the unlicensed EBICS
  module cannot retrieve statements from the last three days. For production use,
  obtain a license from joonis and configure it (see below).

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

## License

GNU Affero General Public License v3.0 (AGPLv3)

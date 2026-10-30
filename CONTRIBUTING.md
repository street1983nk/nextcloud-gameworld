# Contributing

Thanks for helping with Gameworld.

## Getting started

Set up the local development stack as described in [docs/dev-setup.md](docs/dev-setup.md).

Please open an issue before larger changes, so we can agree on the approach first. Security problems go through the private channel in [SECURITY.md](SECURITY.md), never a public issue.

## Local gates before a pull request

All of these must be green:

```sh
uv run ruff check src tests
uv run ruff format --check src tests
PYRIGHT_PYTHON_FORCE_VERSION=latest uv run pyright
uv run vulture
uv run pytest -q -m "not docker"
cd frontend && npm ci && npm run build
```

The frontend checks run as part of pytest (tests/test_frontend_i18n.py).

## Conventions

- Comments and docstrings in English.
- User-visible texts in German, English and French via the i18n dictionaries (frontend/src/i18n for the web interface, src/gameworld/i18n for the backend).
- German texts with real umlauts, no em or en dashes, no emojis.
- Conventional commit messages: feat, fix, docs, test, refactor, chore.

## Licence

Gameworld is licensed under [AGPL-3.0-or-later](LICENSE). Contributions are accepted under the same licence.

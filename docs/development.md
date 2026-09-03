# Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .[test]
pytest -q
ruff check .
```

Layout: `src/subsync/` (package), `tests/` (offline, synthetic fixtures only),
`docs/`, `scripts/`. CI runs pytest + ruff on Linux/Windows/macOS × Python
3.11/3.12 — tests must be offline and deterministic (no real WebDAV, no
subtitle sites; use fixtures and mocks).

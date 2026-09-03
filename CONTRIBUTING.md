# Contributing

## Adding a subtitle source adapter

1. Add an adapter module with `search(number) -> [candidates]` and a detail
   fetch that reports languages + a direct download URL.
2. Report access honestly: a page existing is not `FREE_DIRECT`.
3. Isolate failures — one broken source must not affect others.
4. Add offline tests with synthetic HTML fixtures.

## Tests

All tests must be offline and deterministic. Use fixtures under
`tests/fixtures/` (synthetic SRT/JSON). Never hit real WebDAV or subtitle
sites from tests.

## Lint

```bash
ruff check .
```

## Never commit

- Real subtitle files (`.srt`/`.ass`/`.ssa`) other than synthetic fixtures
- Credentials (`.env`, tokens, cookies)
- Real media inventory, real catalog numbers, or real filenames

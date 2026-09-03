# Subtitle Sources

Each source is an isolated adapter in `src/subsync/`. A source reports one of:
`FREE_DIRECT`, `INDEXED_BUT_NOT_DOWNLOADABLE`, `LOGIN_REQUIRED`,
`CAPTCHA_REQUIRED`, `PAID_ONLY`, or `SOURCE_ERROR` — a page existing is not the
same as a free downloadable subtitle.

| Source | Status | Notes |
|---|---|---|
| subtitlecat.com | working | curl backend (some CDNs reset Python TLS); multi-language detail pages |
| others | audited | see `deep_search.SOURCE_CAPABILITY` — login/CF-gated sources are recorded, never bypassed |

## Adding a source adapter

Implement `search(number) -> [candidates]` and a detail-page fetch that can
report languages and a direct download URL. Register it in the discovery
driver. See [../CONTRIBUTING.md](../CONTRIBUTING.md).

# AV Subtitle Sync v0.1.0

First public release.

## Highlights

- Multi-source subtitle discovery with per-source adapters and honest
  access-type reporting (a page existing is not the same as a free subtitle)
- WebDAV synchronization with a verify-everything upload model:
  fresh PROPFIND protection, exact-filename check, GET roundtrip, SHA256
  equality, and re-parse — for every target
- Subtitle production: exact-number gating, pysubs2 validation, empty-cue
  cleaning, and Traditional → Simplified Chinese conversion (OpenCC)
- Video Group Model V2 — quality variants (normal/4K) and duplicate copies fan
  out safely; edition variants and multipart media are protected by default
- Broken-timeline repair with a strict invalid-ratio gate, plus conservative
  watermark filtering with an audit trail
- Cross-platform (Windows / macOS / Linux) with a doctor command for
  environment diagnostics

## Known limitations

- Playback synchronization still requires human verification (roundtrip
  verification proves bytes, not timeline alignment)
- Multipart media requires manual/special handling; whole-movie subtitles are
  never auto-served to parts
- Subtitle-source availability may change over time; some sources require
  login or impose rate limits
- Windows readiness is code-complete but awaiting CI verification

## Status

Early public release (0.1.0).

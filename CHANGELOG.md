# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-09-03

### Added

- Multi-source subtitle discovery architecture with per-source isolated adapters
- WebDAV storage backend (PROPFIND / curl-GET / PUT) with UTF-8 path support
- Canonical catalog-number parsing from video filenames
- Subtitle production pipeline: exact-number gate, parse validation, empty-cue
  cleaning, and UTF-8 normalization
- Traditional → Simplified Chinese conversion (OpenCC `t2s`) with timeline guard
- Video Group Model V2: SINGLE / QUALITY_VARIANT / DUPLICATE_COPY /
  EDITION_VARIANT / MULTIPART / AMBIGUOUS classification
- Quality-variant and duplicate-copy subtitle fan-out
- Edition-variant guard and manual `approve-variant` flow
- Broken-timeline subtitle repair with a ≤2% invalid-ratio gate
- Conservative watermark filtering with audit trail
- Upload safety chain: fresh PROPFIND protection → PUT → exact-filename check →
  GET roundtrip → SHA256 equality → re-parse
- Per-target `UPLOADED_UNVERIFIED` state; `sync_verified` set only by a human
- `subsync doctor` environment diagnostics
- Cross-platform CLI (Windows / macOS / Linux)
- Offline, deterministic test suite with synthetic fixtures
- GitHub Actions CI across Linux / Windows / macOS × Python 3.11 / 3.12

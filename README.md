# AV Subtitle Sync

A multi-source subtitle discovery, validation, repair and WebDAV synchronization
pipeline for personal media libraries.

## Overview

`subsync` scans a WebDAV-hosted video library, detects canonical catalog numbers
from filenames, searches multiple subtitle sources, produces cleaned and
normalized Simplified Chinese SRT files, and uploads them next to each video —
with a safety-first, verify-everything upload model.

It does **not** distribute media or subtitle files, and it does **not** depend on
any specific cloud provider: any WebDAV server works.

## Features

- Recursive WebDAV inventory (PROPFIND) with video / subtitle / metadata classification
- Catalog-number parsing with site-prefix stripping and zero-padding rules
- Multi-source subtitle search (per-source adapters, isolated failures)
- Conservative watermark filtering (audit trail; mixed cues are kept for review)
- Broken-timeline repair with a strict invalid-ratio gate
- Traditional → Simplified Chinese conversion (OpenCC `t2s`, timeline untouched)
- Variant-group aware fan-out (normal + 4K copies each get their own sidecar)
- Upload canaries: fresh PROPFIND protection, exact-filename check, GET roundtrip,
  SHA256 equality, pysubs2 re-parse — per target
- `sync_verified` is only ever set by a human after watching the video

## Architecture

See [docs/architecture.md](docs/architecture.md).

## Installation

Requires Python ≥ 3.11.

### Windows (PowerShell)

```powershell
git clone <repo-url>
cd av-subtitle-sync
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
Copy-Item .env.example .env
subsync doctor
```

If script activation is blocked, do **not** change your ExecutionPolicy permanently —
call the venv binaries directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\subsync.exe doctor
```

Or run the helper: `scripts/setup_windows.ps1`.

### macOS / Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
subsync doctor
```

## Quick Start

```bash
subsync doctor                      # environment check (read-only)
subsync scan --write                # inventory the library
subsync search --number ABC-001     # discover subtitles for one number
subsync produce --number ABC-001    # build final.zh-CN.srt locally
subsync batch-upload --numbers ABC-001   # plan (dry run)
subsync batch-upload --numbers ABC-001 --execute   # verified upload
subsync verify --number ABC-001     # after you checked it in your player
```

## Configuration

Copy `.env.example` → `.env` and fill in your WebDAV endpoint and credentials.
See [docs/configuration.md](docs/configuration.md).

## WebDAV

Any WebDAV 2.x server works. The storage backend keeps a few compatibility
behaviors as defaults (curl-based GET, Basic auth, UTF-8 percent-encoded paths).

## CLI

`subsync --help` lists all commands. Highlights:

| Command | Purpose | Writes remote? |
|---|---|---|
| `doctor` | environment check | never |
| `scan` | inventory | never |
| `search` | multi-source discovery → local cache | never |
| `produce` | download + clean + validate → local final | never |
| `batch-upload` | plan by default; `--execute` uploads | only with `--execute` |
| `verify` | human confirmation bookkeeping | never |
| `approve-variant` | unlock an edition variant | never (records approval) |
| `repair` | broken-timeline repair (local) | never |
| `deep-search` | alias of `search` | never |

## Subtitle Sources

Enabled adapters live in `src/subsync/` with per-source isolation. Currently:
SubtitleCat (working), plus capability-audited entries for other sites.
See [docs/sources.md](docs/sources.md).

## Subtitle Production

Downloads are gated by exact-number matching, parsed with pysubs2, cleaned of
empty cues, converted with OpenCC when the source is Traditional Chinese, and
re-parsed for verification. Raw sources are never modified. See
[docs/safety.md](docs/safety.md).

## Variant Groups

Numbers with multiple videos are classified into SINGLE / QUALITY_VARIANT /
DUPLICATE_COPY / EDITION_VARIANT / MULTIPART / AMBIGUOUS. Subtitles fan out
only to quality variants and duplicate copies; edition variants require an
explicit `approve-variant`; multipart is never auto-served a whole-movie file.

## Safety

- Never overwrites an existing subtitle (fresh PROPFIND before every write)
- Every PUT is followed by PROPFIND + GET + SHA256 + re-parse
- Uploads start as `UPLOADED_UNVERIFIED`; only you can set `sync_verified`
- Write commands are dry-run by default (`--execute` required)

## Privacy

This project stores runtime data under `data/` (gitignored). It never publishes
your library contents. See [docs/safety.md](docs/safety.md).

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/development.md](docs/development.md).

## Disclaimer

This project does not distribute media or subtitle files. Users are responsible
for complying with copyright law, website terms, and local laws. The project
does not bypass CAPTCHA, paywalls, or authentication.

## License

License: To be selected before public release.

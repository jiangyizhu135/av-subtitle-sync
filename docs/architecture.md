# Architecture

```
Media Library (WebDAV)
     ↓
Inventory Scanner (recursive PROPFIND)
     ↓
Number Parser
     ↓
Subtitle Sources (per-source adapters)
     ↓
Candidate Validator (exact-number gate, parse, ratio gates)
     ↓
Production / Repair (pysubs2, OpenCC, watermark filter)
     ↓
Storage Backend (WebDAV)
     ↓
Upload (protection → PUT → PROPFIND → GET → SHA256 → re-parse)
```

## Video Group Model

One canonical NUMBER can map to several videos. Classification order:

```
NUMBER
├── MULTIPART               part/cd/disc markers (highest priority)
├── QUALITY_VARIANT         _4K / _8K / _1080P … (subtitle fan-out allowed)
├── DUPLICATE_COPY          same basename + size (fan-out allowed, no byte-level claim)
├── EDITION_VARIANT         edition suffixes (standard uploadable; variant needs approval)
├── AMBIGUOUS               unexplained → human decision
└── SINGLE
```

Number normalization ≠ timeline equivalence: two files with the same canonical
number do not automatically share a subtitle unless the group model says so.

## Module map

| Module | Responsibility |
|---|---|
| `settings.py` | PROJECT_ROOT-derived config, .env loading |
| `storage.py` | WebDAV PROPFIND / GET (curl) / PUT (requests) |
| `http_backend.py` | curl / python HTTP backends, auto selection |
| `inventory.py` | video detection, number parsing, subtitle matching |
| `variants.py` | video group classification |
| `subtitles.py` | SubtitleCat adapter + search |
| `deep_search.py` | multi-source discovery driver |
| `production.py` | download → validate → clean → final |
| `repair.py` | broken-timeline repair |
| `srt.py` / `clean.py` | SRT parsing, validation, empty-cue cleaning |
| `cli.py` | command surface |

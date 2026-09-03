# Safety Model

## Upload gate

```
fresh PROPFIND of the parent dir   → existing subtitle? SKIP_EXISTING_SUBTITLE
PUT real-video-basename + ".srt"   → 200/201/204
PROPFIND                           → exact filename present, no "(1).srt" duplicates
GET roundtrip                      → SHA256(local) == SHA256(remote)
pysubs2 re-parse                   → cue count / first / last identical, 0 empty
```

Any failure stops the batch. Successfully uploaded files are never rolled back.

## Verification states

- `UPLOADED_UNVERIFIED`: bytes verified, timeline NOT yet confirmed
- `sync_verified = true`: only set by a human after watching, via `subsync verify`
- Quality variants (normal/4K) are verified independently — never inherited

## Guards

- Multipart numbers are never served a whole-movie subtitle
- Edition variants require explicit `approve-variant`
- Never overwrite, even with `--execute`

## Repair gate

Broken-timeline cues may only be dropped automatically when the invalid ratio
is ≤ 2%. Above that, alternatives are searched; otherwise the number is marked
`MANUAL_REPAIR_REQUIRED`.

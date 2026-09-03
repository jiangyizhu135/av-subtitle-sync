# NFO Generation

`subsync nfo` builds a Kodi / Jellyfin / VidHub compatible `.nfo` movie
sidecar **locally and offline**: no network access, no scraping, and no
remote writes anywhere in the command.

## Usage

```bash
# preview the XML (nothing is written)
subsync nfo --meta meta.json --stdout

# write to data/nfo/<NUMBER>.nfo (default)
subsync nfo --meta meta.json --number ABC-001 --plot plot.txt

# explicit output path / inputs
subsync nfo --meta meta.json --title-info title.json --thumb-map thumbs.json --out out.nfo
```

| Option | Purpose |
|---|---|
| `--meta` (required) | metadata JSON (schema below) |
| `--number` | catalog number; defaults to `meta.number` |
| `--plot` | plain-text plot file; without it `<plot>`/`<outline>` are omitted |
| `--title-info` | optional JSON with a `display_title` (e.g. a Simplified Chinese title) |
| `--thumb-map` | optional JSON object mapping actress name → thumb URL |
| `--out` | output path (default `data/nfo/<NUMBER>.nfo`) |
| `--force` | allow overwriting an existing output file |
| `--stdout` | print the XML instead of writing a file |

## Metadata JSON schema

All fields are optional except that a number must come from `--number` or
`meta.number`. Missing fields are simply omitted from the XML — nothing is
ever invented.

```json
{
  "number": "ABC-001",
  "cid": "abc00001",
  "title": " original title as scraped ",
  "release": "2026-07-31",
  "score": "9.00",
  "runtime": "120",
  "producer": "Studio",
  "director": "Director",
  "actresses": ["Name A", "Name B"],
  "genres": ["genre1", "genre2"],
  "trailer": "https://example/trailer"
}
```

`publish_date` is accepted as an alias for `release`, `actress` for
`actresses`, `genre` for `genres`, and `publisher` for `producer`.

## Title policy

The title policy is stable and load-bearing (media libraries match on it):

| Tag | Content |
|---|---|
| `<title>` | `NUMBER + " " + display title` (Simplified Chinese preferred; falls back to the original title) |
| `<originaltitle>` | original title as scraped |
| `<sorttitle>` | the catalog number |

`<title>` never repeats the number: if the display title already starts with
the same number (`ABC-001 …`, `ABC001 …`, case-insensitive), the redundant
prefix is stripped before composing.

## XML output

Root element is `<movie>`.
Actors are emitted as `<actor><name/><role/><order/>[<thumb/>]</actor>` in
metadata order; genres are written both as `<genre>` and `<tag>`. Identity is
carried by `<uniqueid type="num" default="true">` plus an optional
`<uniqueid type="cid">`.

## Safety

- Generation is a pure function of its inputs: no network I/O.
- The output is re-parsed and root-checked (`<movie>`) before it is written.
- An existing output file is never overwritten unless `--force` is given.
- The command never touches the remote library — uploading sidecars is a
  separate, explicit decision.

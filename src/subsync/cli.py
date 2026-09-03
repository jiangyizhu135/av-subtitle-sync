"""subsync CLI — public interface.

Commands:
  doctor          read-only environment & connectivity check
  scan            recursive PROPFIND inventory + statistics
  search          multi-source subtitle discovery for one number / whole library
  produce         download + validate + clean into final.zh-CN.srt (local only)
  batch-upload    plan by default; --execute performs per-target verified upload
  verify          mark manually confirmed targets as sync_verified
  approve-variant approve an edition variant to reuse the standard subtitle
  repair          repair broken-timeline subtitles locally
  nfo             build a Kodi/Jellyfin-compatible .nfo locally (offline)

Write commands never run by default, and never overwrite existing subtitles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import NoReturn

from subsync import __version__
from subsync.utils import redact_secrets


def _fail(code: str, detail: str = "", debug: bool = False) -> NoReturn:  # type: ignore[name-defined]
    print(f"{code}" + (f": {redact_secrets(detail)}" if detail else ""))
    if debug:
        import traceback
        traceback.print_exc()
    sys.exit(1)


def get_storage():
    from subsync.settings import get_settings
    from subsync.storage import WebDAVStorage
    s = get_settings()
    if not s.webdav_url:
        _fail("STORAGE_CONFIG_ERROR", "WEBDAV_URL 未配置（.env）", args_debug())
    if not s.webdav_username or s.webdav_password is None:
        _fail("STORAGE_CONFIG_ERROR", "WEBDAV_USERNAME / WEBDAV_PASSWORD 未配置（.env）")
    return WebDAVStorage(s.webdav_url, s.webdav_username, s.webdav_password)


def args_debug() -> bool:
    return "--debug" in sys.argv


# ================================================================ doctor
def cmd_doctor(args) -> int:
    """只读体检：Python / 配置 / 数据目录 / curl / WebDAV 认证 / PROPFIND。默认零远端写。"""
    from subsync.http_backend import curl_path
    from subsync.settings import get_settings
    s = get_settings()
    rows = []

    def check(name, ok, note=""):
        rows.append((name, "PASS" if ok else ("CONFIGURATION_REQUIRED" if note == "cfg" else "FAIL"), note))
        return ok

    check("Python", sys.version_info >= (3, 11), sys.version.split()[0])
    check("Configuration", s.configured, "" if s.configured else "cfg")
    check("Data directory", s.data_dir.exists() or s.data_dir.mkdir(parents=True, exist_ok=True) is None)
    check("curl", curl_path() is not None, curl_path() or "not found")
    check("Subtitle sources", True, "subtitlecat adapter ready")

    if s.configured:
        from subsync.storage import WebDAVStorage
        st = WebDAVStorage(s.webdav_url, s.webdav_username, s.webdav_password)
        status, entries, err = st.propfind("", "1")
        check("WebDAV auth", status in (207, 200), err or f"HTTP {status}")
        check("PROPFIND", status == 207 and bool(entries), f"entries={len(entries)}")
    else:
        rows += [("WebDAV auth", "CONFIGURATION_REQUIRED", "cfg"),
                 ("PROPFIND", "SKIPPED", "cfg")]

    print(f"{'Check':<20} {'Result':<24} Note")
    for name, res, note in rows:
        note = redact_secrets(note)
        print(f"{name:<20} {res:<24} {note}")
    print("\nRemote write       NOT TESTED")
    all_pass = all(r == "PASS" for _, r, _ in rows)
    print("READY" if all_pass else "CONFIGURATION_REQUIRED")
    return 0 if all_pass else 2


# ================================================================ scan
def cmd_scan(args) -> int:
    from subsync.inventory import build_inventory_entries, is_metadata_sidecar
    from subsync.settings import get_settings
    st = get_storage()
    files = st.walk("")
    print(f"PROPFIND walk: {len(files)} files")
    entries = build_inventory_entries(files)
    numbers: dict[str, int] = {}
    parse_failed = 0
    with_subs = 0
    parse_failed_list = []
    for e in entries:
        if e.number:
            numbers[e.number] = numbers.get(e.number, 0) + 1
        else:
            parse_failed += 1
            parse_failed_list.append(e.rel)
        if e.subtitles:
            with_subs += 1
    meta_sidecars = sum(1 for f in files if is_metadata_sidecar(f.rel))
    print(f"""
== inventory ==
Total videos      : {len(entries)}
Unique numbers    : {len(numbers)}
Parse failed      : {parse_failed}
Videos w/ subtitle: {with_subs}
Metadata sidecars (listed, ignored for NUMBER): {meta_sidecars}
""")
    if parse_failed_list and args.debug:
        for p in parse_failed_list:
            print(f"  PARSE_FAILED: {p}")
    if args.write:
        inv = {"source": "webdav_propfind",
               "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "videos": [{"rel": e.rel, "name": e.name, "size": e.size,
                           "number": e.number, "subtitles": e.subtitles} for e in entries],
               "files_total": len(files)}
        p = get_settings().inventory_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(inv, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"inventory -> {p}")
    return 0


# ================================================================ search
def cmd_search(args) -> int:
    from subsync.deep_search import EXAMPLE_MULTIPART_PARTS, search_one
    from subsync.settings import get_settings
    s = get_settings()

    def targets() -> list[str]:
        if args.numbers:
            return [n.strip().upper() for n in args.numbers.split(",") if n.strip()]
        inv_p = s.inventory_path
        if not inv_p.is_file():
            print("INVENTORY_MISSING: 先运行 subsync scan --write")
            sys.exit(1)
        inv = json.loads(inv_p.read_text(encoding="utf-8"))
        return sorted({v["number"] for v in inv["videos"] if v.get("number")})

    nums = targets()
    print(f"deep search: {len(nums)} numbers × multi-source（curl/python auto，限速单 worker）")
    for num in nums:
        parts = EXAMPLE_MULTIPART_PARTS.get(num, []) if args.multipart_probe else []
        res = search_one(num, s.deep_search_dir / num, s,
                         use_engine=args.engine_fallback, parts=parts)
        best = res.get("best_candidate")
        sc = res.get("subtitlecat", [{}])[0] if res.get("subtitlecat") else {}
        av = res.get("avsubtitles", [{}])[0] if res.get("avsubtitles") else {}
        best_part = f"{best['source']}/{best['language']}" if best else "-"
        print(f"[{num}] subtitlecat={sc.get('access_type', 'NO_RESULT')} "
              f"avsubtitles={av.get('access_type', 'NO_RESULT')} best={best_part}")
        # per-number summary（produce 的输入）
        sc_list = res.get("subtitlecat", [])
        summary = {"number": num,
                   "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "best_candidate": best,
                   "candidates": [{"title": x.get("notes", "") or "",
                                   "detail_url": x.get("page_url", ""),
                                   "srt_url": x.get("srt_url", ""),
                                   "language": (x.get("languages") or [""])[0] if x.get("languages") else ""}
                                  for x in sc_list if isinstance(x, dict)],
                   "subtitlecat": sc_list,
                   "avsubtitles": res.get("avsubtitles", [])}
        out = s.deep_search_dir / num / "summary.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(args.delay)
    print("\nsearch complete（仅缓存；Remote PUT = 0）")
    return 0


# ================================================================ produce
def cmd_produce(args) -> int:
    from subsync.production import produce_number
    from subsync.settings import get_settings
    s = get_settings()

    if args.numbers:
        numbers = [n.strip().upper() for n in args.numbers.split(",") if n.strip()]
    else:
        if not s.deep_search_dir.is_dir():
            print("SEARCH_RESULTS_MISSING: 先运行 subsync search")
            return 1
        numbers = []
        for d in sorted(s.deep_search_dir.iterdir()):
            if (d / "summary.json").is_file():
                numbers.append(d.name)

    ok, failed = [], []
    for num in numbers:
        summary_file = s.deep_search_dir / num / "summary.json"
        if not summary_file.is_file():
            failed.append({"number": num, "status": "SEARCH_RESULTS_MISSING"})
            continue
        entry = json.loads(summary_file.read_text(encoding="utf-8"))
        r = produce_number(num, entry, s.subtitle_cache, s)
        if r.get("status") == "LOCAL_READY":
            ok.append(num)
        else:
            failed.append(r)
        err = r.get("error") or ""
        print(f"[{num}] {r.get('status')} cues={r.get('cue_count')} "
              f"invalid_removed={r.get('invalid_cues_removed', 0)} "
              f"{('ERR: ' + err) if err else ''}")
    print(f"\nLOCAL_READY: {len(ok)} | failed: {len(failed)}")
    for f in failed:
        print(f"  {f.get('number')}: {f.get('status')} {f.get('error', '')[:120]}")
    print("零远端写：produce 全程本地")
    return 0 if ok or not failed else 1


# ================================================================ batch-upload
def _load_production_manifest(s):
    from subsync.manifest import load_manifest
    return load_manifest(s.manifest_dir / "subtitle_manifest.json")


def _save_production_manifest(s, m):
    from subsync.manifest import save_manifest
    m.setdefault("videos", {})
    save_manifest(m, s.manifest_dir / "subtitle_manifest.json")


def cmd_batch_upload(args) -> int:
    """分批上传。默认 PLAN（只读）；--execute 才执行 PUT。绝不覆盖已有字幕。"""
    import time as _time

    import pysubs2

    from subsync.inventory import subtitle_for
    from subsync.settings import get_settings
    from subsync.utils import normalize_newlines
    from subsync.variants import classify_number_videos

    s = get_settings()
    if not s.configured:
        _fail("STORAGE_CONFIG_ERROR", "WEBDAV_URL / USERNAME / PASSWORD 未配置（.env）", args.debug)
    numbers = [n.strip().upper() for n in args.numbers.split(",") if n.strip()]
    mm = _load_production_manifest(s)
    productions = mm.setdefault("productions", {})
    inv_p = s.inventory_path
    if not inv_p.is_file():
        _fail("INVENTORY_MISSING", "先运行 subsync scan --write", args.debug)
    inv = json.loads(inv_p.read_text(encoding="utf-8"))

    def fail(verdict, completed, failed_at, detail, remaining):
        print(f"\n{verdict}")
        print(f"Completed: {completed}")
        print(f"Failed at: {failed_at} — {detail}")
        print(f"Remaining: {remaining}")
        sys.exit(1)

    # ---- preflight：production LOCAL_READY + final 可解析 ----
    preflight_fail, finals = [], {}
    for number in numbers:
        prod = productions.get(number)
        if not prod or prod.get("status") not in ("LOCAL_READY", "REPAIR_LOCAL_READY"):
            preflight_fail.append(f"{number}: production status={prod and prod.get('status')}")
            continue
        final = s.subtitle_cache / number / "final.zh-CN.srt"
        if not final.is_file():
            preflight_fail.append(f"{number}: final.zh-CN.srt 不存在")
            continue
        data = final.read_bytes()
        try:
            ssa = pysubs2.SSAFile.from_string(
                normalize_newlines(data.decode("utf-8-sig")), format_="srt")
        except Exception as e:
            preflight_fail.append(f"{number}: reopen 失败 {e}")
            continue
        empty = sum(1 for e in ssa.events if e.plaintext.strip() == "")
        if not ssa.events or empty != 0:
            preflight_fail.append(f"{number}: cues={len(ssa.events)} empty={empty}")
            continue
        finals[number] = (final, data, {"cue_count": len(ssa.events),
                                        "first": ssa.events[0].start,
                                        "last": ssa.events[-1].end,
                                        "sha256": hashlib.sha256(data).hexdigest()})
    if preflight_fail:
        print("REPAIR_BATCH_PREFLIGHT_FAILED" if args.repair else "BATCH_PREFLIGHT_FAILED")
        for f in preflight_fail:
            print(f"  {f}")
        sys.exit(1)
    print(f"preflight PASS: {len(finals)}/{len(numbers)}\n")

    from subsync.storage import WebDAVStorage
    st = WebDAVStorage(s.webdav_url, s.webdav_username, s.webdav_password)
    results: list[dict] = []
    completed: list[str] = []
    skipped_numbers: list[tuple[str, str]] = []
    remaining = list(numbers)
    variants_targeted = 0

    class BatchStop(Exception):
        def __init__(self, verdict, detail):
            self.verdict, self.detail = verdict, detail

    def upload_one_variant(number, video, final, data, info, prod, group_kind) -> dict:
        nonlocal variants_targeted
        parent = video["rel"].rsplit("/", 1)[0]
        video_name = video.get("video_name") or video["name"]
        stem = video_name.rsplit(".", 1)[0]
        remote_rel = f"{parent}/{stem}.srt"
        variants_targeted += 1

        # fresh PROPFIND 保护（逐 target；绝不覆盖）
        status, entries, _ = st.propfind(parent, "1")
        if status != 207:
            raise BatchStop("PROPFIND_FAILED", f"{parent} -> {status}")
        present_names = [e.rel.rsplit("/", 1)[-1] for e in entries if not e.is_dir]
        hits_sub = [n for n in present_names if subtitle_for(video_name, n)]
        if hits_sub:
            return {"number": number, "video_rel": video["rel"],
                    "status": "SKIP_EXISTING_SUBTITLE", "detail": f"{hits_sub}"}
        if not args.execute:
            return {"number": number, "video_rel": video["rel"],
                    "status": "PLANNED", "detail": "dry-run（--execute 才 PUT）"}

        status = st.put(remote_rel, data, ctype="application/x-subrip")
        if status not in (200, 201, 204):
            raise BatchStop("PUT_ERROR", f"{number} HTTP {status} -> {remote_rel}")
        status2, entries2, _ = st.propfind(parent, "1")
        names2 = [e.rel.rsplit("/", 1)[-1] for e in entries2 if not e.is_dir]
        _ = status2
        if f"{stem}.srt" not in names2:
            raise BatchStop("REMOTE_FILENAME_MISMATCH",
                            f"未找到 {stem}.srt；现状={[n for n in names2 if stem in n]}")
        dupes = [n for n in names2 if n.startswith(stem) and n != f"{stem}.srt"
                 and n.lower().endswith((".srt", ".ass", ".ssa"))]
        if dupes:
            raise BatchStop("REMOTE_FILENAME_MISMATCH", f"出现自动重名: {dupes}")
        got = st.get(remote_rel)
        if not got:
            raise BatchStop("SHA_MISMATCH", f"{number} GET 为空")
        (s.subtitle_cache / number).mkdir(parents=True, exist_ok=True)
        (s.subtitle_cache / number / "roundtrip.zh-CN.srt").write_bytes(got)
        sha_local = hashlib.sha256(data).hexdigest()
        sha_remote = hashlib.sha256(got).hexdigest()
        if sha_local != sha_remote:
            raise BatchStop("SHA_MISMATCH",
                            f"{number} {sha_local[:12]} vs {sha_remote[:12]}")
        try:
            rssa = pysubs2.SSAFile.from_string(
                normalize_newlines(got.decode("utf-8-sig")), format_="srt")
        except Exception as e:
            raise BatchStop("REMOTE_PARSE_ERROR", f"{number} {e}") from e
        rempty = sum(1 for e in rssa.events if e.plaintext.strip() == "")
        if (len(rssa.events), rempty, rssa.events[0].start, rssa.events[-1].end) != \
           (info["cue_count"], 0, info["first"], info["last"]):
            raise BatchStop("CUE_COUNT_MISMATCH" if len(rssa.events) != info["cue_count"]
                            else "TIMESTAMP_MISMATCH",
                            f"{number} remote 与本地不一致")

        record = {
            "number": number,
            "video_name": video_name,
            "parent_path": "/" + parent,
            "subtitle": {
                "status": "UPLOADED_UNVERIFIED",
                "source": prod.get("source", {}).get("source") or "subtitlecat",
                "source_language": prod.get("source", {}).get("source_language") or "zh-CN",
                "target_language": "zh-CN",
                "translated": prod.get("subtitle", {}).get("translated", False),
                "converted": prod.get("subtitle", {}).get("converted", False),
                "cue_count": info["cue_count"],
                "local_sha256": sha_local,
                "remote_sha256": sha_remote,
                "remote_name": f"{stem}.srt",
                "remote_path": "/" + remote_rel,
                "roundtrip_verified": True,
                "sync_verified": False,
                "uploaded_at": _time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
            "group_type": group_kind,
            "raw_source": str(s.subtitle_cache / number / "source.srt"),
            "local_final": str(final),
            "roundtrip_copy": str(s.subtitle_cache / number / "roundtrip.zh-CN.srt"),
            "uploaded_at": _time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        if prod.get("subtitle", {}).get("converted"):
            record["manual_review_focus"] = ["traditional_to_simplified_conversion"]
        mm.setdefault("videos", {})[video["rel"]] = record
        _save_production_manifest(s, mm)
        print(f"[{number}] PUT {status} {remote_rel} | roundtrip PASS (cues={info['cue_count']})")
        return {"number": number, "video_rel": video["rel"], "remote_rel": "/" + remote_rel,
                "put_status": status, "sha256": sha_remote, "cue_count": info["cue_count"],
                "status": "UPLOADED_UNVERIFIED"}

    for number in numbers:
        if number not in finals:
            if number in remaining:
                remaining.remove(number)
            continue
        final, data, info = finals[number]
        hits = [{"name": v["name"], "rel": v["rel"], "size": v.get("size")}
                for v in inv["videos"] if v.get("number") == number]
        if not hits:
            fail("VIDEO_NOT_FOUND", completed, number, "inventory 无此番号", remaining)
        g = classify_number_videos(number, hits)
        if g.kind == "MULTIPART":
            fail("MULTIPART_NOT_ALLOWED", completed, number, g.reason, remaining)
        if g.kind == "AMBIGUOUS":
            fail("AMBIGUOUS_VIDEO_MATCH", completed, number, g.reason, remaining)
        approved = {a.get("video") for a in productions[number].get("approved_variants", [])}

        prod = productions[number]
        v_uploaded, v_skipped = [], []
        try:
            for var in g.variants:
                if var.get("role") == "EDITION_VARIANT_UNRESOLVED" and \
                        var["video_name"] not in approved:
                    v_skipped.append({"number": number, "video_rel": var["rel"],
                                      "status": "EDITION_SUBTITLE_UNRESOLVED",
                                      "detail": var["video_name"]})
                    continue
                r = upload_one_variant(number, var, final, data, info, prod, g.kind)
                variants = prod.setdefault("variants", [])
                variants[:] = [x for x in variants if x.get("video") != var["video_name"]]
                variants.append({"video": var["video_name"], "subtitle": var["subtitle_name"],
                                 "status": r["status"],
                                 "roundtrip_verified": r["status"] == "UPLOADED_UNVERIFIED",
                                 "sync_verified": False})
                prod["variant_group"] = g.kind == "VIDEO_VARIANT_GROUP"
                prod["variant_count"] = len(g.variants)
                prod["group_type"] = g.kind
                _save_production_manifest(s, mm)
                if r["status"] == "UPLOADED_UNVERIFIED":
                    v_uploaded.append(r)
                    results.append(r)
                else:
                    v_skipped.append(r)
                    print(f"[{number}] {r['status']} {r['detail']}（不覆盖，继续下一 target）")
        except BatchStop as e:
            if v_uploaded:
                prod["status"] = "PARTIAL_VARIANT_UPLOAD"
                _save_production_manifest(s, mm)
            fail(e.verdict, completed, number, e.detail, remaining)

        if v_uploaded:
            completed.append(number)
            if g.kind == "VIDEO_VARIANT_GROUP":
                prod["status"] = "VARIANTS_UPLOADED_UNVERIFIED" if not v_skipped else "PARTIAL_VARIANT_UPLOAD"
            else:
                prod["status"] = "UPLOADED_UNVERIFIED"
            prod["subtitle"]["status"] = prod["status"]
            _save_production_manifest(s, mm)
            if v_skipped:
                skipped_numbers.append((number, f"部分 target 跳过: {[x['status'] + ' ' + x['detail'] for x in v_skipped]}"))
        else:
            skipped_numbers.append((number, f"全部 target 跳过: {[x['status'] for x in v_skipped]}"))
        if number in remaining:
            remaining.remove(number)
        print()

    print("## Upload report\n")
    for r in results:
        print(f"### {r['number']}")
        print(f"Video    : {r['video_rel']}")
        print(f"Subtitle : {r['remote_rel']}")
        print(f"PUT      : {r['put_status']}")
        print("Roundtrip: PASS")
        print(f"Status   : {r['status']} (sync_verified=false)\n")
    for n, why in skipped_numbers:
        print(f"### {n}\n{why}\n")

    failed_count = len(remaining) if remaining else 0
    print(f"""## 安全统计
Numbers requested          : {len(numbers)}
Numbers completed          : {len(completed)}
Remote video targets       : {variants_targeted}
SRT uploaded               : {len(results) if args.execute else 0}
Skipped existing           : {len(skipped_numbers)}
Failed                     : {failed_count}
Roundtrip verified         : {len(results) if args.execute else 0}
sync verified              : 0

## Remote Safety
Videos modified: NO | NFO modified: NO | Poster modified: NO | Backdrop modified: NO
Existing subtitle overwritten: NO | DELETE: 0 | MOVE: 0""")
    if not args.execute:
        print("\nDRY RUN（--execute 才会写入远端）")
    elif not failed_count and not remaining:
        print(f"\nROUND4_BATCH{args.label}_COMPLETED")
    else:
        print("\nROUND4_BATCH_PARTIAL（已成功者不回滚，manifest 如实记录）")


# ================================================================ verify
def cmd_verify(args) -> None:
    """人工（VidHub）确认后：sync_verified=true + by/at。多版本必须 --variant 指定。"""
    import time as _time

    from subsync.settings import get_settings
    s = get_settings()
    mp = s.manifest_dir / "subtitle_manifest.json"
    m = json.loads(mp.read_text(encoding="utf-8")) if mp.is_file() else {"videos": {}}
    number = args.number.upper()
    targets = [(rel, v) for rel, v in m.setdefault("videos", {}).items()
               if v.get("number") == number]
    if args.variant:
        var = args.variant.lower()
        targets = [(rel, v) for rel, v in targets
                   if v.get("video_name", "").lower() == var
                   or v.get("video_name", "").rsplit(".", 1)[0].lower() == var]

        if not targets:
            print(f"VARIANT_NOT_FOUND: {args.variant}")
            sys.exit(1)
    elif len(targets) > 1:
        print(f"MULTIPLE_VARIANTS: {number} 有 {len(targets)} 个视频版本，必须 --variant 指定：")
        for _rel, v in targets:
            print(f"  {v.get('video_name')}")
        sys.exit(1)
    hit = 0
    for _rel, v in targets:
        sub = v["subtitle"]
        if sub.get("status") not in ("UPLOADED", "UPLOADED_UNVERIFIED"):
            print(f"SKIP: {number} 状态 {sub.get('status')} 不可 verify")
            continue
        sub["sync_verified"] = True
        sub["sync_verified_by"] = args.by or "manual_vidhub"
        sub["sync_verified_at"] = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
        sub["status"] = "VERIFIED"
        for prod in m.get("productions", {}).values():
            if prod.get("number") != number:
                continue
            for x in prod.get("variants", []):
                if x.get("video") == v.get("video_name"):
                    x["sync_verified"] = True
                    x["status"] = "VERIFIED"
            if prod.get("variant_group") and prod.get("variants") and all(
                    x.get("sync_verified") for x in prod["variants"]):
                prod["status"] = "VERIFIED"
        hit += 1
        print(f"VERIFIED: {number} / {v.get('video_name')}")
    if mp.is_file() or hit:
        mp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"共 {hit} 条记录更新")


# ================================================================ approve-variant
def cmd_approve_variant(args) -> None:
    """人工确认某 edition variant 可复用标准字幕 → 记录批准（PUT 在后续批次）。"""
    import time as _time

    from subsync.settings import get_settings
    if not args.reuse_standard_subtitle:
        print("需要 --reuse-standard-subtitle（确认复用标准版字幕）")
        sys.exit(1)
    s = get_settings()
    mp = s.manifest_dir / "subtitle_manifest.json"
    if not mp.is_file():
        print("MANIFEST_NOT_FOUND")
        sys.exit(1)
    m = json.loads(mp.read_text(encoding="utf-8"))
    prod = m.setdefault("productions", {}).get(args.number.upper())
    if not prod:
        print(f"PRODUCTION_NOT_FOUND: {args.number}")
        sys.exit(1)
    entry = {"video": args.variant, "reuse_standard_subtitle": True,
             "approved_at": _time.strftime("%Y-%m-%dT%H:%M:%S%z"), "approved_by": args.by}
    approved = prod.setdefault("approved_variants", [])
    approved[:] = [x for x in approved if x.get("video") != args.variant]
    approved.append(entry)
    for x in prod.get("variants", []):
        if x.get("video") == args.variant:
            x["status"] = "EDITION_SUBTITLE_APPROVED"
    mp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"APPROVED: {args.number} / {args.variant}（后续批次允许上传其 .srt）")


# ================================================================ repair
def cmd_repair(args) -> int:
    """坏时间轴字幕修复（本地 canary；ratio gate；零远端写）。"""
    from subsync.repair import repair_number
    from subsync.settings import get_settings
    s = get_settings()
    results = {}
    for num in [n.strip().upper() for n in args.numbers.split(",") if n.strip()]:
        r = repair_number(num, s.subtitle_cache, s)
        results[num] = r
        print(f"[{num}] total={r.get('original_cue_count')} invalid={r.get('invalid_cues')} "
              f"ratio={r.get('invalid_ratio')} -> {r.get('decision')}")
    mp = s.manifest_dir / "subtitle_manifest.json"
    if mp.is_file():
        m = json.loads(mp.read_text(encoding="utf-8"))
        m.setdefault("repairs", {}).update(results)
        mp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print("本地 repair canary 完成（零 PUT）")
    return 0


# ================================================================ nfo
def cmd_nfo(args) -> int:
    """本地生成 .nfo sidecar（纯离线组装；零网络、零远端写）。

    输入是调用方准备好的 metadata JSON（schema 见 docs/nfo.md）；
    输出前重新解析校验 XML；已存在文件不覆盖（--force 才允许）。
    """
    import xml.etree.ElementTree as ET

    from subsync.nfo import build_nfo_bytes
    from subsync.settings import get_settings

    meta_path = Path(args.meta)
    if not meta_path.is_file():
        print(f"META_NOT_FOUND: {meta_path}")
        return 1
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"META_PARSE_ERROR: {e}")
        return 1
    if not isinstance(meta, dict):
        print("META_PARSE_ERROR: metadata JSON 顶层必须是对象")
        return 1

    num = (args.number or meta.get("number") or "").strip().upper()
    if not num:
        print("NFO_NUMBER_MISSING: 用 --number 指定，或在 metadata JSON 中提供 number")
        return 1

    plot = None
    if args.plot:
        plot_path = Path(args.plot)
        if not plot_path.is_file():
            print(f"PLOT_NOT_FOUND: {plot_path}")
            return 1
        plot = plot_path.read_text(encoding="utf-8").strip() or None

    title_info = None
    if args.title_info:
        ti_path = Path(args.title_info)
        if not ti_path.is_file():
            print(f"TITLE_INFO_NOT_FOUND: {ti_path}")
            return 1
        title_info = json.loads(ti_path.read_text(encoding="utf-8"))

    thumb_map = None
    if args.thumb_map:
        tm_path = Path(args.thumb_map)
        if not tm_path.is_file():
            print(f"THUMB_MAP_NOT_FOUND: {tm_path}")
            return 1
        thumb_map = {str(k): str(v) for k, v in
                     json.loads(tm_path.read_text(encoding="utf-8")).items()}

    data = build_nfo_bytes(num, meta, plot,
                           thumb_map=thumb_map,
                           title_info=title_info)
    # 写前校验：重新解析 + 根元素必须是 <movie>
    try:
        root = ET.fromstring(data)
    except Exception as e:
        print(f"NFO_XML_INVALID: {e}")
        return 1
    if root.tag != "movie":
        print(f"NFO_XML_INVALID: root=< {root.tag} >")
        return 1

    if args.stdout:
        print(data.decode("utf-8"))
        return 0

    s = get_settings()
    out = Path(args.out) if args.out else s.data_dir / "nfo" / f"{num}.nfo"
    if out.exists() and not args.force:
        print(f"NFO_EXISTS: {out} 已存在（--force 才允许覆盖）")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"NFO_WRITTEN: {out} ({len(data)} bytes)")
    print("本地生成完成（零远端写；上传另行处理）")
    return 0


# ================================================================ main
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="subsync",
        description="AV Subtitle Sync — multi-source subtitle discovery, validation, "
                    "repair and WebDAV synchronization.")
    ap.add_argument("--version", action="version", version=f"subsync {__version__}")
    ap.add_argument("--debug", action="store_true", help="出错时输出完整 traceback")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="只读环境与连通性检查").set_defaults(func=cmd_doctor)
    p_scan = sub.add_parser("scan", help="递归 PROPFIND 全库清单 + 统计")
    p_scan.add_argument("--write", action="store_true", help="写入 data/inventory/inventory.json")
    p_scan.add_argument("--debug", action="store_true")
    p_scan.set_defaults(func=cmd_scan)

    p_search = sub.add_parser("search", help="多来源字幕发现（只缓存，不上传）")
    p_search.add_argument("--numbers", default=None, help="逗号分隔；缺省=全库唯一番号")
    p_search.add_argument("--engine-fallback", action="store_true", help="搜索引擎发现兜底")
    p_search.add_argument("--multipart-probe", action="store_true", help="对已知分片番号追加 part 查询")
    p_search.add_argument("--delay", type=float, default=1.0)
    p_search.set_defaults(func=cmd_search)

    p_prod = sub.add_parser("produce", help="下载+验证+清理 → final.zh-CN.srt（本地）")
    p_prod.add_argument("--numbers", default=None)
    p_prod.set_defaults(func=cmd_produce)

    p_bat = sub.add_parser("batch-upload", help="分批上传（默认 dry-run；--execute 才写远端）")
    p_bat.add_argument("--numbers", required=True, help="逗号分隔，严格按此顺序处理")
    p_bat.add_argument("--execute", action="store_true", help="显式执行远端 PUT")
    p_bat.add_argument("--label", default="", help="批次标签（仅用于完成提示）")
    p_bat.add_argument("--debug", action="store_true")
    p_bat.set_defaults(func=cmd_batch_upload)

    p_ver = sub.add_parser("verify", help="人工确认后回写 sync_verified=true")
    p_ver.add_argument("--number", required=True)
    p_ver.add_argument("--variant", default=None, help="多版本番号必须指定 video basename")
    p_ver.add_argument("--by", default="manual_vidhub")
    p_ver.set_defaults(func=cmd_verify)

    p_app = sub.add_parser("approve-variant", help="批准 edition variant 复用标准字幕")
    p_app.add_argument("--number", required=True)
    p_app.add_argument("--variant", required=True)
    p_app.add_argument("--reuse-standard-subtitle", action="store_true")
    p_app.add_argument("--by", default="manual")
    p_app.set_defaults(func=cmd_approve_variant)

    p_rep = sub.add_parser("repair", help="坏时间轴字幕本地修复")
    p_rep.add_argument("--numbers", required=True)
    p_rep.set_defaults(func=cmd_repair)

    p_nfo = sub.add_parser("nfo", help="本地生成 .nfo（纯离线组装；零远端写）")
    p_nfo.add_argument("--meta", required=True, help="metadata JSON 路径（schema 见 docs/nfo.md）")
    p_nfo.add_argument("--number", default=None, help="番号；缺省取 metadata JSON 的 number 字段")
    p_nfo.add_argument("--plot", default=None, help="剧情简介文本文件（可选；绝不编造剧情）")
    p_nfo.add_argument("--title-info", default=None,
                       help="标题解析 JSON（display_title 字段优先；可选）")
    p_nfo.add_argument("--thumb-map", default=None,
                       help="演员名→thumb URL 的 JSON 对象文件（可选）")
    p_nfo.add_argument("--out", default=None, help="输出路径（默认 data/nfo/<NUMBER>.nfo）")
    p_nfo.add_argument("--force", action="store_true", help="允许覆盖已存在的输出文件")
    p_nfo.add_argument("--stdout", action="store_true", help="只打印 XML，不写文件")
    p_nfo.set_defaults(func=cmd_nfo)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\nINTERRUPTED")
        return 130
    except Exception as e:
        if args.debug or getattr(args, "debug", False):
            import traceback
            traceback.print_exc()
        code = {
            "CURL_NOT_AVAILABLE": "CURL_NOT_AVAILABLE",
            "CurlUnavailable": "CURL_NOT_AVAILABLE",
        }.get(type(e).__name__, "SUBTITLE_SOURCE_UNAVAILABLE")
        print(f"{code}: {redact_secrets(str(e))[:200]}")
        print("（--debug 查看完整 traceback）")
        return 1


if __name__ == "__main__":
    sys.exit(main())

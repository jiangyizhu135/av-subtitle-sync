# Windows

## Install (PowerShell)

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

If `Activate.ps1` is blocked by execution policy, do not change it permanently.
Call the venv executables directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\subsync.exe doctor
```

`scripts/setup_windows.ps1` automates venv creation and install only.

## Notes

- curl is discovered via `shutil.which("curl")` — Windows 10/11 ships
  `C:\Windows\System32\curl.exe`.
- All subprocess calls use argument lists (no shell), so cmd/PowerShell/bash
  behave identically.
- Remote (WebDAV) paths are always POSIX (`/`-separated strings); local paths
  use `pathlib.Path`. The two never mix.
- All text I/O is explicit UTF-8; JSON is written with `ensure_ascii=False`.

# Configuration

Copy `.env.example` → `.env`. All keys are optional at install time; commands
that need WebDAV will report `STORAGE_CONFIG_ERROR` until configured.

| Key | Meaning |
|---|---|
| `WEBDAV_URL` | WebDAV endpoint whose root is your media root |
| `WEBDAV_USERNAME` / `WEBDAV_PASSWORD` | Basic-auth credentials |
| `WEBDAV_ROOT` | logical root inside the endpoint (default `/`) |
| `HTTP_PROXY` / `HTTPS_PROXY` | optional proxy |
| `SUBSYNC_PREFERRED_LANGUAGES` | language priority (default `zh-CN,zh-TW`) |

`config/config.toml` (optional, gitignored) can hold non-secret defaults.
`config.example.toml` shows the shape.

Paths are always resolved relative to the project root (`PROJECT_ROOT`),
never from the current working directory.

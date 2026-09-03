# Security Policy

## Reporting

Open an issue for non-sensitive problems. For anything containing credentials,
contact the maintainers privately instead.

## What NOT to post in issues

- Passwords, tokens, cookies, `Authorization` headers
- WebDAV credentials or private server URLs
- Full unredacted logs (scrub `password=`, `Authorization:`, URLs with userinfo)

Sanitize logs before pasting: replace credentials with `***` and trim to the
relevant traceback.

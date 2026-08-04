# statichost

A personal library for hosting standalone HTML files — one-off tools/dashboards/trackers Brian
builds for different projects (PT tracking, plot-finder, autoshopper UIs, etc.), all served from
one place instead of scattered files opened locally.

## Architecture

- `app.py` — single-file FastAPI app. No database.
- `CONTENT_DIR` (env, default `./content`; on the deploy VM this is `/srv/www`, volume-mounted per
  `docker-compose.yml`) is where every hosted `.html` file is actually *served from*. **The
  filesystem is the source of truth for what exists** — drop a file in and it appears on the
  homepage automatically.
- `sites/` (in this repo, git-tracked) is where you actually **edit** hosted pages — `_sync_sites()`
  in `app.py` mirrors it into `CONTENT_DIR` on every app startup (local `--reload`, and every VM
  `docker compose up -d --build` after a deploy). This is what makes "edit a sub-site locally,
  `git push`, it's live" true without a separate manual copy step — see the dedicated section below.
  `sites/` only ever supplies page *files*; it never touches `_manifest.json`/`_storage.json`.
- `_manifest.json`, written inside `CONTENT_DIR`, decorates the filesystem listing — per-file title
  override, note, `visible`, `order` — and never touches the hosted HTML itself. Written via
  `POST /api/manifest` from the pencil-icon editor on the homepage (`templates/index.html`).
- Content is served read-only at `/view/{path}` (path-traversal-checked) and `/raw/*` (static mount,
  for assets a hosted page references relatively).
- `/static/*` is a **separate** mount for app-level chrome (the favicon), not user content — don't
  confuse it with `/raw`.
- `CONTENT_DIR` itself (`./content` locally, `/srv/www` on the VM) is **gitignored** — it's a runtime
  mirror + curation state, not source. No system `pip` on this box; the venv is built with `uv`
  (`uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt`).

Full deploy steps (Docker Compose on VM 105, port 8088) are in `README.md` — don't duplicate them
here, just read it before touching deployment.

This repo is now git-tracked, with a git-push-then-remote-reset deploy pipeline to VM 105
(`192.168.0.222`), mirroring `../autoshopper/scripts/deploy.sh`: `scripts/deploy.sh` pushes `main`,
then over SSH does `git fetch` + `reset --hard origin/main` + `docker compose up -d --build` on the
VM. See `docs/deploy.md` for the one-time setup (GitHub remote, SSH key, first checkout) — most of
it is a manual, interactive one-time step (password SSH, creating the GitHub repo), not something
to redo per session.

## Per-page persistent storage — built (2026-08-04)

The manifest only ever tracked *which files show on the homepage* — it had no concept of state
belonging to an individual hosted page. That gap is closed: `app.py` now has a generic per-file
key/value API, following the same philosophy as the manifest (plain JSON next to the content, no
DB):

- `GET /api/storage/{content_path:path}?key={key}` → `{"value": <string-or-null>}`
- `POST /api/storage/{content_path:path}` with body `{"key": ..., "value": <string>}` → `{"ok": true}`
- Backed by a single `_storage.json` next to `_manifest.json`: `{content_path: {key: value}}`.
  **Namespaced by content path** so two unrelated hosted pages can never collide on a key name —
  see `_clean_ns()` in `app.py`.
- Hosted pages call this via `fetch`, not `localStorage` — state survives across browsers/devices
  since this is server-hosted, that's the whole point of building it here instead of leaving the
  file local. A page finds its own `content_path` by parsing its own `/view/...` URL
  (`location.pathname`) — see `PT.html`'s `CONTENT_PATH` for the reference pattern.

## Convention for every hosted content page

1. **Back-to-home button/link near the top of the page**, pointing at `/` — these are pages you
   drill into from the library grid, so they need a way out that isn't the browser back button.
2. **Persist through the storage API above**, not `localStorage`.
3. **Favicon `<link>` tags** — same four tags pointing at `/static/favicon{,-16,-32,-180}.{svg,png}`
   as `templates/index.html`, so the tab icon stays consistent a few clicks deep in the library.

New pages added to the library should follow all three from the start rather than being retrofitted.
`PT.html` is the reference implementation — copy its `sGet`/`sSet`/`CONTENT_PATH`, its `.home-link`,
and its `<head>` favicon links for any new page.

## Local-only deploy button

The homepage has a bottom-left button that POSTs to `/api/deploy`, which shells out to
`scripts/deploy.sh` — same script as the CLI, just triggered from the browser instead of a terminal.
It only renders (and the endpoint only responds instead of 403ing) when `_is_local()` in `app.py`
is true: `LOCAL_DEV=1` in the server's own env, or the request's actual TCP peer is loopback. Set
`LOCAL_DEV=1` in the local dev-run command; **never** set it in `docker-compose.yml` — the VM must
never show this button, since anything else on the LAN can reach it. The endpoint re-checks
`_is_local()` itself rather than trusting the button's visibility, deliberately — don't remove that
check even though it looks redundant with the template-side one.

## sites/ — hosted pages live in this repo now (2026-08-04)

Every "sub-site" (a hosted HTML page/tool) is tracked at `sites/<name>.html` (or a subfolder for
one with its own assets) and shipped by the *same* deploy as the app itself — no separate copy step
onto the server, ever. The whole point: "modify both the website and the specific sub-sites locally
and have them all deployed together" (Brian, 2026-08-04) is just normal `git push` +
`scripts/deploy.sh` now, same as any other code change.

- **Edit `sites/<page>.html` directly** — never hand-edit the copy under `content/`/`/srv/www`,
  it's overwritten by `_sync_sites()` on every restart and your edit would silently vanish.
- Adding a brand new hosted page: drop it in `sites/`, commit, push, deploy — it shows up on the
  homepage automatically (filesystem is still the source of truth for *what exists*), no code
  changes needed anywhere.
- `sites/PT.html` — a daily PT/rehab routine tracker: per-exercise checkboxes, streaks, a month-view
  calendar background, video links, and saved baseline test values. Fully wired to the storage API
  and has the back-to-home link — this is the page to copy from when adding the next one. (Brian's
  original working copy at `../PT.html`, one directory above this repo, still exists but is now
  superseded — `sites/PT.html` is the one that actually ships.)

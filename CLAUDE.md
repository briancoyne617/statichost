# statichost

A personal library for hosting standalone HTML files — one-off tools/dashboards/trackers Brian
builds for different projects (PT tracking, plot-finder, autoshopper UIs, etc.), all served from
one place instead of scattered files opened locally.

## Architecture

- `app.py` — single-file FastAPI app. No database.
- `CONTENT_DIR` (env, default `./content`; on the deploy VM this is `/srv/www`, volume-mounted per
  `docker-compose.yml`) is where every hosted `.html` file lives. **The filesystem is the source of
  truth for what exists** — drop a file in and it appears on the homepage automatically.
- `_manifest.json`, written inside `CONTENT_DIR`, is the *only* server-side state that exists today.
  It decorates the filesystem listing — per-file title override, note, `visible`, `order` — and
  never touches the hosted HTML itself. Written via `POST /api/manifest` from the pencil-icon editor
  on the homepage (`templates/index.html`).
- Content is served read-only at `/view/{path}` (path-traversal-checked) and `/raw/*` (static mount,
  for assets a hosted page references relatively).
- Local dev has no `content/` dir by default — create one and point `CONTENT_DIR` at it, or set it to
  wherever you're testing from.

Full deploy steps (Docker Compose on VM 105, port 8088) are in `README.md` — don't duplicate them
here, just read it before touching deployment.

This repo is now git-tracked, with a git-push-then-remote-reset deploy pipeline to VM 105
(`192.168.0.222`), mirroring `../autoshopper/scripts/deploy.sh`: `scripts/deploy.sh` pushes `main`,
then over SSH does `git fetch` + `reset --hard origin/main` + `docker compose up -d --build` on the
VM. See `docs/deploy.md` for the one-time setup (GitHub remote, SSH key, first checkout) — most of
it is a manual, interactive one-time step (password SSH, creating the GitHub repo), not something
to redo per session.

## Planned: per-page persistent storage

The manifest only tracks *which files show on the homepage* — it has no concept of state belonging
to an individual hosted page. That's the current gap: pages like `PT.html` need to persist their
own data (checked exercises, logged sets, saved settings) across refreshes, and there's nowhere for
that to live yet.

Planned approach, following the same philosophy as the manifest (plain JSON next to the content,
no DB):

- A generic per-file key/value API in `app.py`, e.g. `GET/POST /api/storage/{content_path}/{key}`.
- Backed by JSON on disk (e.g. one file per content path under a `_storage/` folder next to
  `_manifest.json`), **namespaced by content path** so two unrelated hosted pages can never
  collide on a key name.
- Hosted pages call this via `fetch` for anything that should persist. Don't reach for
  `localStorage` — state should survive across browsers/devices since this is server-hosted, that's
  the whole point of building it here instead of leaving the file local.

## Convention for every hosted content page

1. **Back-to-home button/link near the top of the page**, pointing at `/` — these are pages you
   drill into from the library grid, so they need a way out that isn't the browser back button.
2. **Persist through the storage API above**, not `localStorage` — once it exists, hosted pages
   should use it for anything that needs to survive a refresh.

New pages added to the library should follow both from the start rather than being retrofitted.

## First content file: PT.html

- Lives at `../PT.html` (one directory above this repo) — a daily PT/rehab routine tracker:
  per-exercise checkboxes, a week strip, video links, and saved baseline test values.
- It was originally written against a `window.storage.get(key)` / `.set(key, val)` API (see
  `sGet`/`sSet`, currently around line 365) — that's the Claude.ai *artifacts* runtime's storage
  capability, and it does not exist in a normal browser. Today it silently falls back to an
  in-memory `mem` object, so **nothing persists across an actual page refresh** when served from
  statichost.
- To make it work here: point `sGet`/`sSet` at the storage API above instead of `window.storage`,
  and add the back-to-home button per the convention. Then it can be dropped into `CONTENT_DIR`
  like any other hosted file.

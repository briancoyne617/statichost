# TODO

## Deploy pipeline — mostly done, needs your manual one-time steps
`scripts/deploy.sh` + `docs/deploy.md` are written (git init'd locally, git-push-then-remote-reset
onto the Docker VM at 192.168.0.222, same shape as `../autoshopper/scripts/deploy.sh`). Left for
you, because each is interactive/external and not something to do unattended:
- [ ] Create the GitHub repo (`docs/deploy.md` step 1) and `git push -u origin main`.
- [ ] `ssh-copy-id bc@192.168.0.222` so deploy.sh can SSH in without a password prompt.
- [ ] First checkout + `docker compose up -d --build` on the VM (`docs/deploy.md` step 3).

## Favicon
Design a small flat-icon favicon: a little stack/collection of books, similar in style to the
reference Brian shared (2026-08-03) — flat "long-shadow" icon style, solid-color circular backdrop,
2-3 books leaning/stacked together plus a slim item standing tall alongside them (pencil or
bookmark), warm flat color-blocked palette (reference used a sage/teal circle with a mustard pencil
and pink/rose book spines).

- Open question: match the reference's teal/pink palette as-is, or reskin it to statichost's own
  colors (`--accent:#2B2BE6` indigo / cream `--bg:#F7F5F0`, see `templates/index.html`) so it reads
  as this site's mark rather than a generic stock icon.
- Deliverables: favicon in the sizes a modern `<head>` needs (16x16, 32x32, apple-touch-icon 180x180)
  plus an SVG source, wired into `templates/index.html`.
- Once it exists, reuse the same favicon on hosted content pages (PT.html etc.) for consistent
  branding when you're a few clicks deep in the library.

## Per-page storage + navigation (from CLAUDE.md)
- Build the generic per-file storage API in `app.py` (`/api/storage/{content_path}/{key}` shape),
  JSON-backed, namespaced per content path so hosted pages can't collide on key names.
- Add a back-to-home link/button near the top of every hosted content page.
- Rewire `PT.html`'s `sGet`/`sSet` off of `window.storage` (Claude-artifacts-only API, doesn't exist
  in a real browser — currently falls back to in-memory and loses state on refresh) onto the new
  storage API, then drop it into `CONTENT_DIR`.

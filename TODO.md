# TODO

## sites/ — hosted pages now live in the repo — done (2026-08-04)
Brian: "Add PT.html to the repo and make sure it's automatically included in the right location
upon deployment. I want to be able to modify both the website and the specific sub-sites locally
and have them all deployed together." Implemented as a new `sites/` folder (git-tracked) that
`_sync_sites()` in `app.py` mirrors into `CONTENT_DIR` on every app startup — never touches
`_manifest.json`/`_storage.json`, only page files. Consequence: a deploy (which always ends in a
container restart) ships app code *and* sites/ together automatically, with zero new steps in
`scripts/deploy.sh` — the existing pipeline already does exactly the right thing once the app itself
knows to sync on boot.
- `sites/PT.html` added (copied from `../PT.html`, which still exists but is now superseded — the
  one that actually ships is `sites/PT.html`; edit that one going forward).
- Verified locally: deleted `content/PT.html` and `content/_storage.json`'s absence would've been
  the tell, restarted the server, confirmed `content/PT.html` reappeared byte-for-byte from
  `sites/PT.html` while the *existing* `_storage.json` (real test data) was left untouched.
- `CONTENT_DIR` (`content/` locally, `/srv/www` on the VM) stays gitignored — it's the runtime
  mirror + curation state now, `sites/` is the source.

## Deploy pipeline — button tried, VM-side setup still incomplete (2026-08-04)
`scripts/deploy.sh` + `docs/deploy.md` are written (git init'd locally, git-push-then-remote-reset
onto the Docker VM at 192.168.0.222, same shape as `../autoshopper/scripts/deploy.sh`). Status:
- [x] GitHub repo created + pushed (`origin` → `git@github.com:briancoyne617/statichost.git`, `main`
  pushed and matches `origin/main`).
- [x] `~/.ssh/config` has a `statichost-vm` alias (→ `bc@192.168.0.222`) and passwordless SSH to it
  works (verified: `ssh statichost-vm hostname` → `docker-server`, no prompt).
- [x] `STATICHOST_VM=statichost-vm` exported in `~/.bashrc`.
- [ ] **Brian clicked Deploy — failed**: `cd: /opt/statichost: No such file or directory`. Step 3
  (first checkout on the VM) was never done. Investigated further and found a *second* blocker
  behind it: `bc` isn't in the VM's `docker` group (`docker ps` as `bc` → permission denied on the
  socket), and `sudo` prompts for a password every time (no `NOPASSWD`) — so `scripts/deploy.sh`
  (no `sudo` in its `docker compose` call, by design, for non-interactive use) can't work yet even
  once the directory exists.
- [ ] **Deploy path switched from `/opt/statichost` to `/home/bc/statichost`** — Brian pointed out a
  copy of the app *already* exists at `/home/bc/statichost` (turned out to be a stale, non-git copy
  from the original manual setup in `README.md`, including one leftover unrelated file,
  `content/index.html`, that isn't actually served — `docker-compose.yml` mounts `/srv/www`, not
  this checkout's own `content/`). `/opt` never had a strong reason to exist here the way it did for
  autoshopper's dedicated system user — Docker is already the isolation boundary — so `/home/bc`
  avoids needing `sudo` for the checkout itself, only for the docker-group fix. Updated
  `scripts/deploy.sh`'s `APP` default and `docs/deploy.md` step 3 accordingly (now: `usermod -aG
  docker`, re-login, `mv` the old copy aside — not delete — then fresh `clone` + first
  `up -d --build`). Still needs Brian's password interactively for the `usermod`, so it's his to run.
- [ ] **`/srv/www` on the VM already has real content** (`_manifest.json`, a `content/` subfolder)
  from the original manual setup in `README.md` — didn't investigate further or touch it. Worth a
  `sudo docker ps -a` check before the first `docker compose up` from the new checkout, in case a
  `library`-named container is already running there and would collide (`docker-compose.yml` also
  names its container `library`).

**Heads up:** everything from today's session (storage API, deploy button, favicon, PT.html
streaks/calendar) is still **uncommitted** — only the original initial commit has been pushed. Since
`deploy.sh`/the deploy button only push and reset to *commits*, clicking Deploy right now would be a
no-op against the VM (nothing new to push) rather than actually shipping today's work. Commit first.

## Favicon — done, redesigned after feedback (2026-08-04)
First version was a circle badge (indigo bg) with 3 upright book-spines + a pencil tucked behind
them — Brian's read: "looks like a thumbs up, unrecognizable." Looking at the original reference
image again (`/home/brian/.claude/image-cache/.../1.png`) surfaced what the first pass missed: a
flat *closed* book lying underneath the upright spines, which the first draft never included, plus
the reference has no circle. Rebuilt `static/favicon.svg` accordingly: **no background shape at
all** (transparent), a flat rose-pink base book spanning nearly the full width with a cream page-edge
sliver, two upright spines (plum + pink) standing on it, and a clearly-separated diagonal yellow
pencil (dark tip, yellow shaft, cream ferrule, pink eraser) leaning on the left — sized to fill the
64x64 canvas edge-to-edge rather than sitting small inside a badge.

**Real bug found and fixed in the generation pipeline, not just a design pass:** the PNGs
(`static/favicon-{16,32,180}.png`) are rendered by loading the SVG into a headless-Chromium page and
screenshotting it — no ImageMagick/cairosvg available in this environment. The *first* attempt did
this via `page.setContent()` + `<img src="file://...">`, which silently failed to load the image at
all (Chromium blocks a blank-origin synthetic page from loading `file://` resources) — so every
generated PNG was actually a faithful, perfectly-valid screenshot of Chromium's own **broken-image
placeholder glyph**, not the artwork. That's why every validity check *except* an actual visual
render kept passing (CRC32, zlib inflate, byte-for-byte HTTP transfer, even `new Image()`'s
load/decode event and `naturalWidth` — a PNG of a broken-image icon is still a perfectly valid PNG).
Fixed by generating via **real HTTP navigation** (`page.goto('http://localhost:8001/')`, same-origin
as `/static/favicon.svg`, so the SVG actually loads) instead of `setContent()`. A second, smaller
issue followed: capturing via an *element* screenshot baked the page's cream body background into
the "transparent" areas instead of preserving alpha — fixed by forcing `background:transparent` on
`html`/`body` and taking a full-viewport screenshot with `omitBackground:true` instead of an element
crop. Verified for real this time: injected `<img>` elements into the live same-origin page, confirmed
`load` events with correct `naturalWidth`/`naturalHeight`, decoded the PNG bytes directly (corner
pixel is `RGBA(0,0,0,0)` — genuinely transparent), and visually confirmed the actual artwork renders
cleanly against both white and dark backgrounds with no leftover box edge.

**Second design pass (2026-08-04, same day):** Brian sent a second, clearer reference image and two
notes — "looks like the book is falling off" and "make the bottom book have the paper visible not
the binding." Root causes: the upright books + pencil cluster wasn't well-centered over the base
book (uneven margins read as unstable/sliding), and the base book was a solid rose rect with only a
small cream sliver at one end, reading as a plain block rather than a book. Rebuilt: base book is
now a maroon/crimson cover (`#A8324A`) with a cream page-block (`#F7ECD9`) inset within it — visible
pages framed by cover, not a flat color. Both upright books recolored into the same maroon/crimson
family (`#6B2C3D` dark, `#B23A52` bright) instead of the previous plum+pink, and the whole cluster
recentered directly over the base book's span. Regenerated PNGs the same (now-proven) way. Not yet
redeployed — this round was local-only pending Brian's OK on the look.

**Third pass:** the dark left book, drawn as a plain upright rect, read as tipping *left* (away from
the stack) rather than leaning right into the taller book — a classic "leaning books" look needs an
actual tilt, not just proximity. Added `transform="rotate(9 25 46)"` (pivoting on its own
bottom-center, which sits on the base book) so its top leans right against the taller book instead.

**Fourth pass:** Brian: "still leaning left" after the 9° fix. Verified the rotation math in
isolation first (a standalone render with ruler lines) — it was genuinely correct, tilting right.
The actual cause: the pencil (at -36°) crosses right over the book's top-left corner, and the two
diagonals visually merge into what reads as one continuous *left*-leaning edge, regardless of the
book's own (correct) rotation — confirmed by rendering the full composition at high zoom. Tried
separating them with a gap first (moving the pencil left clipped its tip off the 64x64 canvas;
shortening the pencil instead still left enough contact to read ambiguous). What actually worked:
leave the pencil alone and increase the book's lean to **16°** — strong enough to read unambiguously
as "leaning right" even where the pencil touches it, rather than trying to eliminate the contact.

**Fifth pass — replaced hand-coded shapes with a traced vector (2026-08-07):** hand-tuning rotation
angles on flat `<rect>`s kept fighting optical illusions (see fourth pass) without ever matching the
reference closely enough. Brian ran the reference image through an image-to-SVG tool (Recraft AI, via
a `.psd`) and dropped the result in as `image.psd(1).svg` — smooth bezier paths, gradient-shaded
spines, both upright books at matching height, a pencil with a rounded cap/tip instead of a sharp
point. Cleaned it up rather than hand-redrawing: stripped the ~13KB embedded C2PA provenance
`<metadata>` blob (irrelevant to a favicon, pure bloat), removed one stray gradient-filled rect left
over in the top-left corner (an artifact of the source crop, bounded to x[0,26] y[0,26]), and padded
the viewBox from `0 0 127 137` to `-5 0 137 137` so it's square — the PNG generator stretches the SVG
to fill a square viewport, so a non-square viewBox would otherwise get silently squashed ~7%
vertically. This is now `static/favicon.svg`; PNGs regenerated via the same real-navigation pipeline
from the second pass. Committed and deployed (`d08e494`) — verified live against the VM by `curl`ing
`/static/favicon.svg` and matching it byte-for-byte against the local file.

## Deploy button: git-status checklist + difftastic diff preview — done (2026-08-11)
Brian: "Rip the git status and difftastic code from ../autoshopper, add it to deploy functionality
here." Ported from `../autoshopper/ui/app.py` (`_git_dirty`, `_find_difft`, `_git_status_files`,
`_git_diff_preview`, `_to_win_path`, the `/dev/git-status`+`/dev/git-diff`+`/dev/deploy` trio) and
`../autoshopper/ui/templates/dev.html` (the deploy modal's checklist/diff-toggle/ANSI-to-HTML JS,
`scripts/difft_wrap.sh`) — same shape, adapted to this app's own layout and visual language:
- **Backend** (`app.py`): the deploy button's plain `confirm()` used to fire `/api/deploy` with no
  visibility into what was actually about to ship — fine when the tree was clean, a real trap
  when it wasn't (this bit us earlier this same session during the favicon work: the button
  would've said "deployed" while the VM stayed on stale code, since nothing was committed yet).
  Now: `index()` also computes `_git_dirty()` (best-effort `git status --porcelain`, local-only)
  and passes it to the template. `/api/git-status` returns the changed-file list, each tagged with
  a category via `_FILE_CATEGORIES` (Backend code / Hosted pages / Templates / static / Scripts /
  Docs / Other — matches this repo's own top-level layout, not autoshopper's). `/api/git-diff`
  builds a full working-tree diff: tracked changes go through git's `--ext-diff` machinery via
  `scripts/difft_wrap.sh` (a WSL→Windows difft.exe shim, copied over unchanged apart from doc
  comments pointing at `app.py`/`index.html` instead of `ui/app.py`/`dev.html`), untracked files
  get diffed against an empty temp file so they show as a full addition. Falls back to plain
  `git diff --color=always` when difftastic isn't installed — never raises, never blocks a deploy.
  `/api/deploy` now takes optional `commit_message`/`files` form fields: when a message is given,
  it `git add`s exactly the checked files (never `git add -A`) and commits before running
  `scripts/deploy.sh`, so unchecking a row in the sheet genuinely leaves it out of the commit.
- **New dependency**: `Form(...)` params need `python-multipart`, which FastAPI only imports
  lazily — a clean venv (or a freshly-built Docker image) crashes at import time without it, not
  at request time, so it surfaced immediately on `--reload` here. Added to `requirements.txt`
  (same comment as autoshopper's own copy, which had already hit this). No Dockerfile change
  needed — `COPY requirements.txt .` + `pip install` already picks up a new line on the next
  `--build`.
- **Frontend** (`templates/index.html`): reused the existing `.sheet`/`.panel` bottom-sheet
  pattern (the curate editor already established it) for the new deploy sheet instead of
  introducing autoshopper's separate `.deploy-modal` look — one modal shape per app, not two.
  Added a `deployNow()` that only opens the sheet when `GIT_DIRTY` (server-rendered); a clean tree
  still gets the original one-click `confirm()` path, unchanged. Checklist groups by category with
  per-row "all"/"none", a lazy-loaded "Show diff" toggle (widens the panel, since difftastic's
  side-by-side needs real columns), and a small hand-rolled ANSI SGR→HTML converter for the diff
  pre block (difftastic and plain `git diff --color=always` both only ever emit basic 16-color
  codes, so no library needed). New CSS custom properties (`--amber`, `--green`, plus a full
  `--ansi-*` palette, light+dark) added alongside the existing `--accent`/`--accent-2` tokens.
  Extended the page's existing `esc()` helper to also escape `>` (needed for the diff text, wasn't
  needed by the editor's own use of it before now).
- Verified end to end against the local dev server with Playwright: dirty-tree FAB shows the amber
  dot and correct title; opening the sheet loads and correctly categorizes the actual changed files
  from this session's own work; per-category "all"/"none" toggle checkboxes correctly; Escape
  closes the sheet; "Show diff" loads a real difftastic side-by-side render (confirmed via
  screenshot — proper syntax highlighting, correct old/new columns) and widens the panel; empty
  commit message is blocked by the same `alert()` guard as autoshopper's.
- **Deliberately not yet committed/deployed** — this changes what the deploy button itself does,
  so it gets the same "verify locally first" treatment as everything else this session, and a
  meta-change like this is worth Brian's own eyes on before it ships.

## PT.html: per-set click-through + one-click hold timer — done (2026-08-10)
Brian: "For things that are timed, add a one click timer (no seconds or anything, just a bar moving
across the top or something elegant), and for things with multiple sets, have clicking it need to
happen that many times to fully check and show progress via the check box filling up."
- Every `EXERCISES` entry with a "N ×" dose now carries an explicit `sets` field (and `hold` in
  seconds for the ones that are a timed hold, e.g. `'2 × 45s hold'` → `sets:2, hold:45`) — added as
  data rather than parsed out of the free-text `dose` string at render time, since the dose text has
  too many shapes (`'5s hold × 10 / foot'` reverses the order) to parse reliably and the array
  already carries per-exercise metadata this way.
- `dayLog[e.id]` now holds either a number (sets completed so far) or `true` (fully done — also what
  a completed item gets normalized to, so it stays compatible with every log ever written before
  this feature existed). `doneCount()`/`isFullyDone()` are the only things that read it; `summarize()`
  (streaks, week strip, calendar month-wall) was updated to go through `isFullyDone()` instead of raw
  key presence.
- The checkbox (`.tick`) got a `.tick-fill` layer that grows from 0–100% height as sets complete,
  clipped to the tick's rounded corners. Tapping a card with `sets>1` advances the count by one and
  fills proportionally; tapping a fully-filled card resets it to zero (same "tap to undo" as before).
- Exercises with `hold` get a thin `.ex-bar` across the card's top edge instead of an instant
  increment: tap starts it, a CSS `width` transition runs it from 0→100% over `hold` seconds, and
  completion auto-advances one set (bar resets, ready for the next). Deliberately a live-hold aid, not
  a stopwatch log — tapping again *while it's running cancels it*, there's no way to skip the wait.
  No numeric countdown shown, per the "no seconds or anything" ask.
- `renderSession()` now calls a new `clearAllTimers()` before rebuilding `#sessionBody`'s HTML —
  needed because day/track navigation and even unrelated edits (video URL, trim fields) all rebuild
  every card from scratch, and a `setTimeout` left pointing at an about-to-be-detached card would
  otherwise fire later and silently write a stray set-completion against whatever day happened to be
  open by then.
- **Verified past data is unaffected before shipping** (Brian asked explicitly): wrote a fake
  legacy-shaped log (`{"tib-raise":true}`, the exact shape every session before this feature produced)
  onto a past date via the storage API directly, reloaded, and confirmed it still renders fully
  checked (100% fill, counted correctly in the day's arch total) — `_storage.json` itself is untouched
  by any deploy regardless (gitignored, lives in the `CONTENT_DIR` volume, never touched by
  `_sync_sites()`), so shipping this only changes how *new* taps are interpreted, never past records.
- Verified interactively with Playwright against the local dev server: a 3-set non-timed exercise
  (Tibialis raises) fills 33%→67%→100%→resets across four taps; a 5×10s timed exercise (Grip
  squeezes) starts the bar on tap, cancels cleanly on a second tap mid-run, and auto-completes one set
  (20% fill) after running the full 10s uninterrupted.

## Per-page storage + navigation — done (2026-08-04)
- `app.py`: generic per-file storage API, `GET/POST /api/storage/{content_path}/{key}`, JSON-backed
  (`_storage.json`), namespaced per content path.
- `PT.html`: `sGet`/`sSet` rewired off `window.storage` onto the new API (`CONTENT_PATH` derived
  from `location.pathname`, falls back to in-memory if opened outside statichost). Verified with a
  real browser reload against the live server — state survives it now.
- `PT.html`: `‹ LIBRARY` back-to-home link added top-left, points at `/`.
- Both are the reference pattern for the *next* hosted page — copy `PT.html`'s approach rather than
  re-deriving it.
- Still open: reuse the favicon (once built) on hosted pages too, per the Favicon item above.

## PT.html: streaks + month-wall calendar — done, several rounds of feedback (2026-08-04)
Final shape, after multiple redirects from Brian:
- **Fixed page background** (`#calBg`/`#calBgGrid`, `position:fixed`, `pointer-events:none`,
  `.wrap` given `z-index:1` to sit above it) — a wall of small month-tiles, **purely
  backward-looking**: the current month (only up to today, no future tail) and then as many
  previous months as it takes to fill the viewport edge-to-edge. No fixed count — dynamically
  estimated from `window.innerWidth/innerHeight` in `estimateCalBgMonthCount()` (roughly 90+ months
  on a big desktop monitor). Only the most recent `CAL_BG_LABEL_MONTHS` (12) get a month-abbreviation
  label, no year anywhere; older tiles are bare dots. Dots are 14px (3x the first draft, per Brian:
  "about three times the current size"). `align-content:space-between` on `.cal-bg-grid` so the
  first/last row sit flush against the top/bottom edges instead of leaving a gap at the bottom.
- Two streak **pills**, fixed top-right (`#streakHud`) — gold (consecutive fully-completed days),
  bronze (consecutive days with *any* effort).

**Two real bugs found and fixed while building this, not just polish:**
1. *Stale-render race* — `renderCalendar`/`renderStreak` are fired fresh on every checkbox toggle
   without awaiting the previous call; rapid-fire toggling could let an older, slower render finish
   *after* a newer one and stomp the DOM with stale data. Fixed with a render-token guard
   (`calRenderToken`/`streakRenderToken`) — each call only writes if it's still the most recent by
   the time it resolves.
2. *N+1 fetch storm* — going purely backward (no future months to skip) plus a dynamically-large
   month count meant every visible day needed its own storage lookup: ~1000+ individual HTTP
   requests on first load, which silently never finished in reasonable time (looked identical to
   "broken" — empty grid, no console errors). Fixed by adding a bulk-read endpoint,
   `POST /api/storage-bulk/{content_path}`, and a client-side `warmLogCache()` that prefetches an
   entire date range in one round trip; `logFor()` is now effectively a cache hit for anything
   pre-warmed. Both `renderCalendar` and `renderStreak` warm their own range up front.

Both re-verified end to end against the live server after the fixes: rapid-firing every toggle for
today settles correctly and survives a real reload; a 1920x1080 viewport renders ~91 fully-populated
tiles with no leftover "future" styling anywhere.

**Known nit, not fixed:** the background's current-month tile sits right behind the old 7-day
`.week` strip, so there's a bit of visual overlap right at the top of the page. Flagged for Brian to
decide: drop the old week strip (redundant with the background + streaks now), or reposition/mask
the background there.

**Also worth noting:** Brian initially saw none of this because he'd loaded the *live VM deployment*
(nothing pushed there yet — see the deploy-pipeline section above) rather than the local dev server
this was actually being iterated on. Local dev runs via `.venv` (created with `uv`, since this box
has no system `pip`) — `CONTENT_DIR=./content SITE_TITLE="..." LOCAL_DEV=1 .venv/bin/uvicorn app:app --port 8001`.

## Local-only deploy button — done (2026-08-04)
A button on the homepage (bottom-left FAB, mirrors the pencil-edit FAB) that POSTs to a new
`/api/deploy`, which shell-execs `scripts/deploy.sh` — same script, same blast radius as running it
by hand, just skips the terminal round-trip.
- **Gated twice, independently:** the button only renders server-side when `_is_local(request)` is
  true (`LOCAL_DEV=1` env var, or the request's actual TCP peer is `127.0.0.1`/`::1`) — set
  `LOCAL_DEV=1` in the local dev-run command; it's never set in `docker-compose.yml`, so it's off by
  default on the VM. The `/api/deploy` endpoint re-checks the *same* condition itself before doing
  anything — a hidden button is UI, not a security boundary, so the check can't live only there.
  Whoever's on the LAN hitting the deployed instance never sees the button and can't invoke the
  endpoint even by calling it directly.
- Confirms via `confirm()` before firing (it pushes to git and restarts the live service), then
  shows a toast with the result — success or the captured script output on failure.
- Verified end to end against the live dev server: button renders when `LOCAL_DEV=1`, confirm-flow
  fires the request, and — since `STATICHOST_VM` isn't exported yet (see deploy-pipeline section) —
  it correctly shows "STATICHOST_VM isn't set" rather than attempting anything. Haven't verified a
  *real* deploy end-to-end yet since that also needs the GitHub repo + SSH key steps above done first.

"""
A dynamic index for a folder of standalone HTML files.

Scans CONTENT_DIR for .html files, renders them as panels, and lets you curate that list from
the page itself — a discreet pencil, bottom right, toggles an editor where you set which files
show and what each is called.

Why this exists instead of plain nginx: nginx can serve the files but cannot *remember* anything,
so "which are visible" and "what is this called" have nowhere to live. That state is the whole
feature, so it needs somewhere to persist — `_manifest.json`, written next to the content.

Design rules that matter:
  - The FILESYSTEM is the source of truth for what exists; the manifest only decorates it. Drop a
    file in the folder and it appears on its own (visible by default). Delete one and it vanishes,
    leaving a harmless orphan entry rather than a broken tile.
  - Default titles come from each file's own <title>, so a curated name is an override, not a
    chore you must do before the page reads well.
  - Content is served read-only and never executed; this only ever reads the directory listing.
  - Hosted pages get their own persistence too, via `/api/storage/{their-own-path}` — a flat
    key/value store per page, namespaced by path so two pages can't collide on a key name, backed
    by `_storage.json` next to the manifest. This is for a page's own state (checkboxes, logs), not
    for anything the manifest already owns (title/visibility/order).
  - `sites/` (in this repo, git-tracked) mirrors into CONTENT_DIR on every startup — see
    `_sync_sites()`. That's how editing a hosted page becomes a normal part of "commit, push,
    deploy" instead of a separate manual copy step onto the server.
"""
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

CONTENT_DIR = Path(os.environ.get("CONTENT_DIR", "./content")).resolve()
MANIFEST = CONTENT_DIR / "_manifest.json"
STORAGE = CONTENT_DIR / "_storage.json"
SITE_TITLE = os.environ.get("SITE_TITLE", "Library")
_REPO_ROOT = Path(__file__).parent
DEPLOY_SCRIPT = _REPO_ROOT / "scripts" / "deploy.sh"
SITES_DIR = _REPO_ROOT / "sites"


def _sync_sites():
    """Mirror sites/ (tracked in git — the pages you actually edit) into CONTENT_DIR (the live
    serving dir, which also holds _manifest.json/_storage.json — never touched here, only page
    files are copied). Runs once at import time, so it fires on every app start: local `--reload`,
    and on the VM every `docker compose up -d --build` after a deploy. sites/ is the source of
    truth for a page's *content*; CONTENT_DIR's copy is a deployed artifact, always overwritten —
    don't hand-edit a page there and expect it to survive a restart."""
    if not SITES_DIR.is_dir():
        return
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    for src in SITES_DIR.rglob("*"):
        if src.is_file():
            dest = CONTENT_DIR / src.relative_to(SITES_DIR)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)


_sync_sites()

app = FastAPI(title="statichost")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# App-level assets (favicon etc) — distinct from /raw, which is hosted CONTENT, not app chrome.
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def _load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text())
    except Exception:
        return {}


def _save_manifest(data: dict):
    MANIFEST.write_text(json.dumps(data, indent=2, sort_keys=True))


def _load_storage() -> dict:
    try:
        return json.loads(STORAGE.read_text())
    except Exception:
        return {}


def _save_storage(data: dict):
    STORAGE.write_text(json.dumps(data, indent=2, sort_keys=True))


def _is_local(request: Request) -> bool:
    """The deploy button only makes sense — and is only safe — on the dev box, never on the
    deployed VM (which is reachable by anything else on the LAN). `LOCAL_DEV=1` is the explicit,
    reliable signal (set by the dev-run command, never set in docker-compose.yml on the VM); the
    loopback check is a convenience fallback for whenever that wasn't set. Checked again, not just
    trusted from the button's visibility, inside the /api/deploy handler itself — a hidden button
    is not a security boundary."""
    if os.environ.get("LOCAL_DEV") == "1":
        return True
    client = request.client
    return bool(client) and client.host in ("127.0.0.1", "::1")


def _clean_ns(content_path: str) -> str:
    """The hosted page's own path, used purely as a namespace key (never touches the filesystem) —
    so two unrelated pages using the same key name (e.g. both calling something 'log') can't clobber
    each other."""
    p = content_path.strip("/")
    if not p or ".." in p.split("/"):
        raise ValueError("bad content path")
    return p[:200]


def _title_of(path: Path) -> str:
    """The file's own <title>, else a readable form of its filename.

    Read a bounded prefix — <title> lives in the head, and some of these pages are large.
    """
    try:
        m = _TITLE_RE.search(path.read_text(errors="ignore")[:4000])
        if m:
            t = re.sub(r"\s+", " ", m.group(1)).strip()
            if t:
                return t[:120]
    except Exception:
        pass
    return path.stem.replace("-", " ").replace("_", " ").title()


def _discover() -> list[dict]:
    """Every .html under CONTENT_DIR, decorated with its manifest entry.

    Sorted by the manifest's `order` when set, then by newest-modified — so a fresh drop surfaces
    at the top without needing to be curated first.
    """
    man = _load_manifest()
    out = []
    for p in sorted(CONTENT_DIR.rglob("*.html")):
        rel = p.relative_to(CONTENT_DIR).as_posix()
        if rel == "index.html" or p.name.startswith("_"):
            continue
        entry = man.get(rel, {})
        st = p.stat()
        out.append({
            "path": rel,
            "title": entry.get("title") or _title_of(p),
            "note": entry.get("note", ""),
            "visible": entry.get("visible", True),
            "order": entry.get("order", 9999),
            "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
            "kb": max(1, st.st_size // 1024),
        })
    out.sort(key=lambda e: (e["order"], -datetime.strptime(e["modified"], "%Y-%m-%d").timestamp()))
    return out


@app.get("/")
async def index(request: Request, edit: int = 0):
    items = _discover()
    local = _is_local(request)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "site_title": SITE_TITLE,
        "items": items if not edit else items,          # editor shows hidden ones too
        "visible_items": [i for i in items if i["visible"]],
        "edit": bool(edit),
        "show_deploy": local,
        "git_dirty": _git_dirty() if local else False,
    })


def _git_dirty() -> bool:
    """True if the working tree has anything `git add -A` would pick up. Best-effort — a git
    failure here just means the dirty-indicator/commit-prompt doesn't show; it does NOT gate the
    deploy route itself, which re-decides for real from the commit_message it's actually given."""
    try:
        status = subprocess.run(["git", "status", "--porcelain"], cwd=str(_REPO_ROOT),
                                capture_output=True, text=True, timeout=10)
        return bool(status.stdout.strip())
    except Exception:
        return False


def _find_difft() -> str | None:
    """difftastic, if installed — structural diff, much easier to skim before a deploy than a
    raw unified diff. This dev box has it via `winget install difftastic` (a Windows install
    reached from WSL through the kernel's binfmt interop, since it's not in apt and there's no
    passwordless sudo here to add it) rather than a native Linux binary — so PATH alone won't
    find it even once installed, and the winget package path is versioned, so it's globbed
    rather than hardcoded. Re-checked on every call, not cached at import time, so
    installing/upgrading it doesn't need an app restart to take effect. Returns None (never
    raises) when it's missing — callers fall back to plain `git diff`."""
    import shutil, glob
    for name in ("difft", "difft.exe"):
        found = shutil.which(name)
        if found:
            return found
    matches = glob.glob("/mnt/c/Users/*/AppData/Local/Microsoft/WinGet/Packages/"
                        "Wilfred.difftastic_*/difft.exe")
    return matches[0] if matches else None


_DIFFT_WRAP = _REPO_ROOT / "scripts" / "difft_wrap.sh"

# Buckets for the deploy sheet's file checklist — first match wins, "Other" is the catch-all.
# Matches this repo's own top-level layout (see CLAUDE.md): sites/ is hosted-page content,
# distinct from the app's own backend/template code even though both are just "code" to git.
_FILE_CATEGORIES = [
    ("Backend code",       lambda p: p.endswith(".py")),
    ("Hosted pages",       lambda p: p.startswith("sites/")),
    ("Templates / static", lambda p: p.startswith("templates/") or p.startswith("static/")),
    ("Scripts",            lambda p: p.startswith("scripts/")),
    ("Docs",               lambda p: p.startswith("docs/") or p.endswith(".md")),
]


def _categorize_file(path: str) -> str:
    for name, test in _FILE_CATEGORIES:
        if test(path):
            return name
    return "Other"


def _git_status_files() -> list:
    """Parsed `git status --porcelain`, one entry per changed path, with the category the deploy
    sheet groups it under. Renames ("R  old -> new") collapse to just the new path — good enough
    for a checklist that's about what changes, not full rename tracking."""
    out = subprocess.run(["git", "status", "--porcelain"], cwd=str(_REPO_ROOT),
                         capture_output=True, text=True, timeout=10).stdout
    files = []
    for line in out.splitlines():
        if not line.strip():
            continue
        code, rel = line[:2].strip() or "??", line[3:].strip()
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        files.append({"path": rel, "status": code, "category": _categorize_file(rel)})
    return files


@app.get("/api/git-status")
def git_status(request: Request):
    """File checklist for the deploy sheet — see templates/index.html. Separate from
    /api/git-diff because the checklist needs to render before anyone asks for the (slower,
    difftastic-shelling-out) diff, and populating it shouldn't wait on that."""
    if not _is_local(request):
        return JSONResponse({"error": "not available"}, status_code=403)
    try:
        return JSONResponse({"files": _git_status_files()})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _to_win_path(posix_path: str) -> str:
    """Windows-style path for a POSIX one — required before handing ANY path to difft.exe (see
    _find_difft): WSL's binfmt interop lets you exec a Windows binary from a Linux shell but
    does not translate its argv, so a raw /mnt/c/... or /tmp/... path is meaningless to it.
    wslpath handles both (a real drive path for /mnt/c, a \\\\wsl.localhost\\...\\ UNC path for
    anything WSL-internal — verified difft.exe can read a /tmp file through that). Falls back to
    the original path on any failure, which just means that one diff comes back empty rather
    than the whole preview failing."""
    try:
        r = subprocess.run(["wslpath", "-w", posix_path], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or posix_path
    except Exception:
        return posix_path


def _git_diff_preview() -> str:
    """Everything `git add -A` would pick up, as one readable diff — tracked changes vs HEAD
    plus untracked files (each diffed against an empty file so a brand-new file shows as a full
    addition instead of being silently skipped, which plain `git diff` does for anything not yet
    in the index). Read-only: never runs `git add`, so previewing the diff can't itself change
    what a later commit picks up.

    Tracked changes go through git's own --ext-diff machinery (scripts/difft_wrap.sh), because
    git already handles extracting the HEAD blob into a temp file per changed path —
    reimplementing that with `git show HEAD:path` here would just be a worse copy of what git
    already does correctly, including renames/deletes."""
    difft = _find_difft()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(_REPO_ROOT),
                            capture_output=True, text=True, timeout=10).stdout
    if not status.strip():
        return "Working tree is clean — nothing to diff."
    parts = []
    if difft:
        env = dict(os.environ, DIFFT_EXE=difft, GIT_EXTERNAL_DIFF=f"bash {_DIFFT_WRAP}")
        tracked = subprocess.run(["git", "diff", "--ext-diff", "HEAD", "--"],
                                 cwd=str(_REPO_ROOT), capture_output=True, text=True,
                                 timeout=60, env=env)
    else:
        tracked = subprocess.run(["git", "diff", "--color=always", "HEAD", "--"],
                                 cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=30)
    if tracked.stdout.strip():
        parts.append(tracked.stdout.strip())
    elif tracked.stderr.strip():
        parts.append(f"[git diff stderr]\n{tracked.stderr.strip()}")

    for line in status.splitlines():
        if not line.startswith("??"):
            continue
        rel = line[3:].strip()
        full = str(_REPO_ROOT / rel)
        if difft:
            import tempfile
            fd, empty_path = tempfile.mkstemp(prefix="statichost_diff_empty_")
            os.close(fd)
            try:
                d = subprocess.run([difft, "--color=always", "--display=side-by-side",
                                    "--width=220", _to_win_path(empty_path), _to_win_path(full)],
                                   capture_output=True, text=True, timeout=20)
                body = d.stdout or d.stderr
            finally:
                os.unlink(empty_path)
        else:
            d = subprocess.run(["git", "diff", "--color=always", "--no-index", "--",
                                os.devnull, rel], cwd=str(_REPO_ROOT), capture_output=True,
                               text=True, timeout=20)
            body = d.stdout or d.stderr
        parts.append(f"+++ new file: {rel} +++\n{body.strip()}")
    return "\n\n".join(parts) or "Working tree is clean — nothing to diff."


@app.get("/api/git-diff", response_class=PlainTextResponse)
def git_diff(request: Request):
    """Diff preview behind the deploy sheet's "Show diff" toggle — see templates/index.html.
    Same local-only gate as the deploy button itself; this is read access to source code, not a
    new capability, but it's still dev-box-only like everything else the deploy button gates."""
    if not _is_local(request):
        return PlainTextResponse("not available", status_code=403)
    try:
        return PlainTextResponse(_git_diff_preview())
    except Exception as e:
        return PlainTextResponse(f"Could not build diff: {e}", status_code=500)


@app.post("/api/deploy")
def deploy(request: Request, commit_message: str = Form(""), files: list[str] = Form([])):
    """Runs scripts/deploy.sh (push + remote reset + rebuild) so 'ship what I'm looking at' is a
    button instead of a terminal round-trip. Same script, same blast radius as running it by hand
    — this is convenience, not a new capability. Declared `def`, not `async def`, so FastAPI runs
    the (blocking, tens-of-seconds) subprocess in its worker threadpool rather than freezing the
    event loop for every other request while a deploy is in flight.

    deploy.sh's own push step is deliberately the ONLY way committed code reaches the VM (reset
    --hard there, never a merge) — but "Everything up-to-date" while the tree sits full of
    uncommitted work is confusing enough to hit for real: the button says "deployed" and the VM
    genuinely is, just not with what's on screen (this bit us during the favicon work this same
    session — the fix that time was committing by hand first). `commit_message`, when non-blank,
    stages exactly `files` (the checked rows from the deploy sheet's checklist, see
    templates/index.html) and commits before deploying — never `git add -A` blindly, so
    unchecking something in the sheet actually leaves it out."""
    if not _is_local(request):
        return JSONResponse({"error": "not available"}, status_code=403)
    vm = os.environ.get("STATICHOST_VM")
    if not vm:
        return JSONResponse(
            {"error": "STATICHOST_VM isn't set in this server's environment — export it and restart."},
            status_code=400,
        )
    commit_message = commit_message.strip()
    if commit_message:
        if not files:
            return JSONResponse({"ok": False,
                "output": "No files selected to commit."}, status_code=400)
        try:
            subprocess.run(["git", "add", "--"] + files, cwd=str(_REPO_ROOT), check=True,
                            capture_output=True, text=True, timeout=30)
            commit = subprocess.run(
                ["git", "commit", "-m", commit_message],
                cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=30,
            )
            if commit.returncode != 0:
                return JSONResponse({"ok": False, "output":
                    "git commit failed:\n" + commit.stdout + commit.stderr}, status_code=500)
        except subprocess.CalledProcessError as e:
            return JSONResponse({"ok": False, "output":
                "git add failed:\n" + (e.stdout or "") + (e.stderr or "")}, status_code=500)
        except subprocess.TimeoutExpired:
            return JSONResponse({"ok": False,
                "output": "git add/commit timed out"}, status_code=504)
    try:
        proc = subprocess.run(
            ["bash", str(DEPLOY_SCRIPT), vm],
            cwd=str(DEPLOY_SCRIPT.parent.parent),
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or "") + (e.stderr or ""))[-4000:]
        return JSONResponse({"ok": False, "output": out + "\n[timed out after 180s]"}, status_code=504)
    output = (proc.stdout + proc.stderr)[-4000:]
    prefix = f"Committed as {commit_message!r}\n\n" if commit_message else ""
    return JSONResponse({"ok": proc.returncode == 0, "output": prefix + output},
                        status_code=200 if proc.returncode == 0 else 500)


@app.post("/api/manifest")
async def save(request: Request):
    """Persist the curated list. Only ever writes decoration — never touches the HTML itself."""
    body = await request.json()
    man = _load_manifest()
    for row in body.get("items", []):
        path = row.get("path")
        if not path:
            continue
        man[path] = {
            "title": (row.get("title") or "").strip()[:120],
            "note": (row.get("note") or "").strip()[:200],
            "visible": bool(row.get("visible", True)),
            "order": int(row.get("order", 9999)),
        }
    _save_manifest(man)
    return JSONResponse({"ok": True, "count": len(body.get("items", []))})


@app.get("/api/storage/{content_path:path}")
async def storage_get(content_path: str, key: str):
    """A hosted page's own persistence — the piece the manifest never covered. Namespaced by the
    page's path so `PT.html`'s 'log' key can never collide with some other page's 'log' key."""
    try:
        ns = _clean_ns(content_path)
    except ValueError:
        return JSONResponse({"error": "bad path"}, status_code=400)
    data = _load_storage()
    return JSONResponse({"value": data.get(ns, {}).get(key[:200])})


@app.post("/api/storage/{content_path:path}")
async def storage_set(content_path: str, request: Request):
    try:
        ns = _clean_ns(content_path)
    except ValueError:
        return JSONResponse({"error": "bad path"}, status_code=400)
    body = await request.json()
    key = str(body.get("key", ""))[:200]
    value = body.get("value")
    if not key or not isinstance(value, str) or len(value) > 200_000:
        return JSONResponse({"error": "bad key/value"}, status_code=400)
    data = _load_storage()
    data.setdefault(ns, {})[key] = value
    _save_storage(data)
    return JSONResponse({"ok": True})


@app.post("/api/storage-bulk/{content_path:path}")
async def storage_bulk_get(content_path: str, request: Request):
    """One round trip for many keys — a page that needs a lot of small pieces of its own history
    at once (PT.html's month-wall background can span hundreds of days) shouldn't have to make
    one HTTP request per day to build it."""
    try:
        ns = _clean_ns(content_path)
    except ValueError:
        return JSONResponse({"error": "bad path"}, status_code=400)
    body = await request.json()
    keys = body.get("keys", [])
    if not isinstance(keys, list) or len(keys) > 3000:
        return JSONResponse({"error": "bad keys"}, status_code=400)
    ns_data = _load_storage().get(ns, {})
    return JSONResponse({"values": {str(k)[:200]: ns_data.get(str(k)[:200]) for k in keys}})


@app.get("/view/{path:path}")
async def view(path: str):
    """Serve a content file. Resolves inside CONTENT_DIR or 404s — no traversal out of the folder."""
    target = (CONTENT_DIR / path).resolve()
    if not str(target).startswith(str(CONTENT_DIR)) or not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(target)


# Assets referenced *by* the hosted pages (images, css) resolve relative to /view/.
if CONTENT_DIR.is_dir():
    app.mount("/raw", StaticFiles(directory=str(CONTENT_DIR)), name="raw")

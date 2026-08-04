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

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

CONTENT_DIR = Path(os.environ.get("CONTENT_DIR", "./content")).resolve()
MANIFEST = CONTENT_DIR / "_manifest.json"
STORAGE = CONTENT_DIR / "_storage.json"
SITE_TITLE = os.environ.get("SITE_TITLE", "Library")
DEPLOY_SCRIPT = Path(__file__).parent / "scripts" / "deploy.sh"
SITES_DIR = Path(__file__).parent / "sites"


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
    return templates.TemplateResponse("index.html", {
        "request": request,
        "site_title": SITE_TITLE,
        "items": items if not edit else items,          # editor shows hidden ones too
        "visible_items": [i for i in items if i["visible"]],
        "edit": bool(edit),
        "show_deploy": _is_local(request),
    })


@app.post("/api/deploy")
def deploy(request: Request):
    """Runs scripts/deploy.sh (push + remote reset + rebuild) so 'ship what I'm looking at' is a
    button instead of a terminal round-trip. Same script, same blast radius as running it by hand
    — this is convenience, not a new capability. Declared `def`, not `async def`, so FastAPI runs
    the (blocking, tens-of-seconds) subprocess in its worker threadpool rather than freezing the
    event loop for every other request while a deploy is in flight."""
    if not _is_local(request):
        return JSONResponse({"error": "not available"}, status_code=403)
    vm = os.environ.get("STATICHOST_VM")
    if not vm:
        return JSONResponse(
            {"error": "STATICHOST_VM isn't set in this server's environment — export it and restart."},
            status_code=400,
        )
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
    return JSONResponse({"ok": proc.returncode == 0, "output": output}, status_code=200 if proc.returncode == 0 else 500)


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

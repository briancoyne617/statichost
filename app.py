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
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

CONTENT_DIR = Path(os.environ.get("CONTENT_DIR", "./content")).resolve()
MANIFEST = CONTENT_DIR / "_manifest.json"
SITE_TITLE = os.environ.get("SITE_TITLE", "Library")

app = FastAPI(title="statichost")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def _load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text())
    except Exception:
        return {}


def _save_manifest(data: dict):
    MANIFEST.write_text(json.dumps(data, indent=2, sort_keys=True))


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
    })


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

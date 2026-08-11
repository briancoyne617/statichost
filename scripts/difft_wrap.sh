#!/usr/bin/env bash
#
# GIT_EXTERNAL_DIFF shim for a Windows difft.exe reached through WSL's binfmt interop.
#
# That interop lets you EXEC a .exe directly from a Linux shell, but it does NOT translate
# argv for you (only the wsl.exe-from-Windows direction does that) — and git hands an external
# diff program a path to its OWN ephemeral blob temp file for the "old" side, which usually
# lives under /tmp, a path a native Windows process has no concept of at all. `wslpath -w`
# fixes both: it turns any WSL-visible path into something difft.exe can actually open — a
# real drive path for anything under /mnt/c, or a \\wsl.localhost\...\ UNC path for anything
# WSL-internal (verified: difft.exe reads a plain /tmp file fine once translated that way).
#
# git invokes an external diff program as:
#   <this> path old-file old-hex old-mode new-file new-hex new-mode [rename-old rename-new]
# See app.py's _git_diff_preview(), which sets DIFFT_EXE and GIT_EXTERNAL_DIFF=bash+this
# path before running `git diff --ext-diff`.
set -euo pipefail
old="$(wslpath -w "$2")"
new="$(wslpath -w "$5")"
# side-by-side (difftastic's default) needs real width to render two columns instead of
# collapsing to single-column — there's no TTY here for it to detect, so it's pinned wide
# to match the deploy sheet's own widened state (see templates/index.html's toggleDiff()).
exec "$DIFFT_EXE" --color=always --display=side-by-side --width=220 "$old" "$new"

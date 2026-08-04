# Deploying statichost to the VM (192.168.0.222)

Mirrors the pattern in `../autoshopper/scripts/deploy.sh`: the VM only ever receives committed,
pushed code, and redeploying is one command. The difference here is this app runs in **Docker**
(already true per the existing `Dockerfile`/`docker-compose.yml`), so the remote step is
`docker compose up -d --build` instead of a systemd restart — there's no venv, no dedicated system
user, no unit file to write. Docker itself already provides the process isolation autoshopper's
`autoshopper` system user was standing in for.

## Why this is simpler than it sounds

There are **no secrets anywhere in this repo** — `app.py` takes only `CONTENT_DIR` and `SITE_TITLE`
env vars, both non-sensitive, and the actual hosted files + `_manifest.json` live on the VM's
`/srv/www` bind mount, outside the git repo entirely. That means:

- The GitHub repo can be **public** with zero exposure — skip generating a deploy key, skip
  `github.com/.../settings/keys` entirely, just `git clone https://github.com/...` on the VM with
  no auth at all. (If you'd rather keep it private out of habit, that's fine too — just add a
  read-only deploy key on the VM the same way autoshopper's doc describes, one extra step.)
- `git reset --hard origin/main` on the VM can never touch your hosted content or its curation —
  they're not part of the tree it resets.

## One-time setup

### 1. Create the GitHub repo and push (from WSL)

```bash
# via the web UI: github.com/new → name it "statichost", public, no README/gitignore (repo exists locally already)
git remote add origin git@github.com:briancoyne617/statichost.git   # or https://github.com/... if public + no key set up
git push -u origin main
```

(No `gh` CLI in this environment to script the repo creation — do this one from the browser or
install `gh` and run `gh repo create briancoyne617/statichost --public --source=. --push`.)

### 2. Passwordless SSH from WSL → the VM

Deploy needs to run non-interactively, so a password prompt defeats the point. From WSL:

```bash
ssh-copy-id bc@192.168.0.222        # prompts once for bc's password, installs your pubkey
ssh bc@192.168.0.222 hostname       # should succeed with no prompt now
```

This is interactive (needs your typed password), so run it yourself rather than through Claude —
type `! ssh-copy-id bc@192.168.0.222` at the prompt if you want to do it from right here.

Then name it in `~/.ssh/config` so the deploy target is a word, not an IP:

```
Host statichost-vm
    HostName 192.168.0.222
    User bc
```

`export STATICHOST_VM=statichost-vm` in your shell profile and `scripts/deploy.sh` takes no args.

### 3. First checkout on the VM

**`/home/bc/statichost`, not `/opt`.** Unlike autoshopper (which runs bare on a venv and wanted a
dedicated system user + root-owned `/opt` for that reason), this app runs in Docker — Docker itself
is the isolation boundary, so there's nothing `/opt` + a separate owner would add. `bc` already owns
`/home/bc`, so the checkout needs no `sudo` at all (only the docker-group fix below does, and that's
one-time regardless of path).

**Check what's already running first.** If `/srv/www` already has real content in it (a
`_manifest.json`, hosted files) from the manual setup in `README.md`, a container may already be up
under the name `library` — `docker-compose.yml` also names its container `library`, so a fresh
`docker compose up` from a new checkout can collide with it. `sudo docker ps -a` before doing
anything else. (If there's already a *non-git* copy of this repo sitting at `/home/bc/statichost`
from before this pipeline existed — plausible, since that's exactly where the manual setup in
`README.md` would have put it — don't `rm -rf` it blind: `mv` it aside first, e.g.
`mv /home/bc/statichost /home/bc/statichost.bak`, so nothing is lost if it turns out to matter.)

**`bc` needs to be in the `docker` group, not just have `sudo`.** Verified on this VM (2026-08-04):
`bc` has `sudo` but it prompts for a password every time (no `NOPASSWD` entry), and `bc` was *not*
in the `docker` group — `docker ps` as `bc` failed with `permission denied` on the socket.
`scripts/deploy.sh` (and the deploy button) run `docker compose` with no `sudo` and need it to be
fully non-interactive, so this has to be fixed before either will work:

```bash
ssh bc@192.168.0.222
command -v git || sudo apt install -y git      # docker + compose are already there per README

sudo usermod -aG docker bc                      # one-time, needs your password
exit                                            # group membership needs a fresh login to take effect
ssh bc@192.168.0.222
docker ps                                       # should now work with no sudo, no error

mv /home/bc/statichost /home/bc/statichost.bak 2>/dev/null   # only if something's already there
git clone https://github.com/briancoyne617/statichost.git /home/bc/statichost   # public repo, no key needed
cd /home/bc/statichost
docker compose up -d --build
```

`docker-compose.yml`'s volume (`/srv/www:/content`) is unchanged — point it at wherever your HTML
already lives, same as the manual setup in `README.md`.

## Day to day

Editing a hosted page (`sites/PT.html`, or any future one) ships through this exact same pipeline —
there's no separate "now copy the file onto the server" step. `_sync_sites()` in `app.py` mirrors
`sites/` into `CONTENT_DIR` on every app startup, and a deploy always ends in a restart
(`docker compose up -d --build`), so a page edit and an app-code edit deploy identically:

```bash
scripts/deploy.sh                 # push + redeploy in one command, once STATICHOST_VM is exported
scripts/deploy.sh bc@192.168.0.222 # or pass the target explicitly, no env var needed
```

Or click **Deploy** on the homepage itself (bottom-left) instead of switching to a terminal — it
runs the exact same script. That button only appears when the server sees `LOCAL_DEV=1` in its own
environment (or a loopback request), so it never shows up on the deployed instance:

```bash
CONTENT_DIR=./content SITE_TITLE="..." LOCAL_DEV=1 STATICHOST_VM=bc@192.168.0.222 \
  uvicorn app:app --reload
```

Local iteration otherwise is untouched — run `uvicorn app:app --reload` (with `CONTENT_DIR` pointed
at a local test folder) and look at `localhost:8000`/`8001` same as always. The VM is only for
"this is done, put it where my phone/other devices can reach it."

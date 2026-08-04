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

```bash
ssh bc@192.168.0.222
command -v git || sudo apt install -y git      # docker + compose are already there — you're
                                                 # already running this app's container per README
sudo mkdir -p /opt/statichost && sudo chown bc:bc /opt/statichost
git clone https://github.com/briancoyne617/statichost.git /opt/statichost   # add a deploy key first if you made it private
cd /opt/statichost
docker compose up -d --build
```

`docker-compose.yml`'s volume (`/srv/www:/content`) is unchanged — point it at wherever your HTML
already lives, same as the manual setup in `README.md`.

If `bc` isn't already in the `docker` group, `sudo usermod -aG docker bc` (then log out/in) so
`docker compose` doesn't need `sudo` — `scripts/deploy.sh` assumes it doesn't.

## Day to day

```bash
scripts/deploy.sh                 # push + redeploy in one command, once STATICHOST_VM is exported
scripts/deploy.sh bc@192.168.0.222 # or pass the target explicitly, no env var needed
```

Local iteration is untouched — run `uvicorn app:app --reload` (with `CONTENT_DIR` pointed at a
local test folder) and look at `localhost:8000` same as always. The VM is only for "this is done,
put it where my phone/other devices can reach it."

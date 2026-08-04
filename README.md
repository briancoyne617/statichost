# library — a dynamic index for a folder of HTML files

Panels for every `.html` under the content folder, curated from the page itself: a discreet
pencil (bottom right) opens an editor for which files show and what each is called.

**Why not plain nginx:** nginx serves the files but can't *remember* anything, and "which are
visible / what is this called" is the whole feature. That state lives in `_manifest.json`, written
next to your content.

## Deploy on the Docker VM (105)

```bash
# copy this folder to the VM, then, if the old nginx container is still up, free the port:
sudo docker rm -f statichost

sudo docker compose up -d --build
```

Browse `http://<vm105-ip>:8088/`. Point the volume at wherever your HTML already is (defaults to
`/srv/www`), and set `SITE_TITLE` in `docker-compose.yml`.

### If `docker compose` isn't found or errors on a plugin

The Compose v2+ plugin is a binary Docker discovers under `cli-plugins/`, and two things trip it:

- **It must be executable.** A hand-downloaded `docker-compose` is not `+x` by default, so Docker
  reports `Invalid Plugins: compose … permission denied`.
- **`sudo` reads root's config, not yours.** A plugin dropped in `~/.docker/cli-plugins/` is
  invisible to `sudo docker`, which looks in `/root/.docker/` — so `sudo docker compose` shows no
  compose command at all. Install it **system-wide** so both see it:

```bash
sudo mkdir -p /usr/local/lib/docker/cli-plugins
# if you already downloaded it into ~/.docker, just move it:
sudo mv ~/.docker/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
sudo docker compose version
```

### Or skip Compose entirely

It's one container — plain docker needs no plugin:

```bash
sudo docker build -t library .
sudo docker run -d --name library --restart unless-stopped \
  -p 8088:8080 -e SITE_TITLE="Brian's Library" \
  -v /srv/www:/content library
```

To stop running docker with `sudo` at all: `sudo usermod -aG docker $USER`, then log out and back in.

## How it behaves

- **The filesystem is the source of truth.** Drop a file in, it appears (visible, titled from its
  own `<title>`). Delete one, it vanishes. The manifest only decorates — a stale entry for a
  deleted file is inert, not a broken tile.
- **Curated names are overrides**, not a prerequisite: the page reads well before you touch it.
- **Subfolders are included** (`notes/wireguard.html` shows up on its own).
- Files starting with `_` are skipped, which is why `_manifest.json` never lists itself.
- New/newest files sort first until you set an order in the editor.

## Notes

- Content is served read-only via `/view/<path>`, resolved inside the content dir — no traversal out.
- **No authentication.** LAN-only; reach it over WireGuard rather than a port-forward. If it ever
  needs to be public, put Caddy in front for HTTPS + basic-auth.
- Backing up is `cp -r` — it's files plus one small JSON.

# Deployment

This project is self-hosted on an Unraid server and deployed with a **GitHub
Actions self-hosted runner**. It replaced an earlier custom webhook (since
removed), which had no concurrency control and re-ran the slow data precompute on
every code push.

## Two workflows

- **`.github/workflows/deploy.yml`** — on push to `main` (or manual dispatch):
  builds the API and Streamlit images and restarts both containers. Does **not**
  touch data. `concurrency: cancel-in-progress` means a newer push supersedes an
  in-flight deploy (the thing the webhook couldn't do).
- **`.github/workflows/refresh-data.yml`** — on a daily schedule (or manual
  dispatch): runs `scripts/precompute.py` in a one-shot container against the
  shared data volume. Independent of the API container, so a deploy mid-refresh
  doesn't kill it and the API keeps serving the old data until new files land.

Splitting these is the whole point: **a code push is fast and never triggers the
~hours-long comeback precompute.**

## Containers and paths

| Container       | Image           | Port | Notes                                   |
|-----------------|-----------------|------|-----------------------------------------|
| `nbaautoreport` | `nbaautoreport` | 8000 | FastAPI; served at `nbastats.jglws.com` |
| `nbastats`      | `nbastats`      | 8501 | Streamlit; served at `nbaautoreport.jglws.com` |

API data directory (single source of truth): **`/mnt/user/appdata/nbaautoreport/data`**
(host) → `/app/data` (container), `DATA_DIR=/app/data`. This is a real, persistent
Unraid path, so volume binds resolve correctly from the host docker daemon.

## Self-hosted runner requirements

The workflows use `runs-on: [self-hosted]` and shell out to `docker`. The runner
must:

1. Be **registered to the `JaGaLopez/NBAautoreport` repo** (GitHub personal-account
   runners are per-repo; an existing runner registered to another repo will not
   pick these up). Either run a second runner instance for this repo, or — better
   for scaling to more projects — move repos under a GitHub org and use org-level
   runners.
2. Have the **host Docker socket** (`/var/run/docker.sock`) and the `docker` CLI
   available (same as the existing portfolio runner).
3. Be able to bind the host path `/mnt/user/appdata/nbaautoreport/data`. Because
   `docker run -v` sources are resolved by the **host** daemon, this must be a real
   host path (it is). The dir already exists and is populated.
4. Carry the default `self-hosted` label (or update `runs-on` to match its labels).

No repo secrets are required by the workflows themselves (the runner's
registration token is configured at runner setup, not in the workflow).

## First-time / cutover steps

1. Register the runner for this repo (above).
2. Trigger **Deploy** (push to `main` or run it manually) and confirm both
   containers come up and `https://nbastats.jglws.com/teams/2024-25` returns 200.
3. If `/mnt/user/appdata/nbaautoreport/data` were ever empty, run **Refresh data**
   once manually to populate it. (It is currently populated, so this is a no-op.)
4. The webhook code has been removed from the repo. To finish decommissioning on
   the server: stop/remove the `nbaautoreport-webhook` container and disable its
   autostart, and optionally delete the push webhook in the repo's GitHub settings.

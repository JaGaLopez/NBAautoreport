#!/bin/bash
set -e

REPO="${REPO_PATH:-/mnt/user/websites/NBAautoreport}"

# Host path for the precomputed JSON the API serves. This MUST be an absolute
# path on the Docker host: the `-v` source below is resolved by the host daemon,
# not inside this (webhook) container, so it must not be derived from $REPO
# (which is the in-container checkout path, e.g. /repo). Keep it on a persistent
# Unraid share so it survives container rebuilds and reboots.
DATA_HOST="${DATA_HOST_PATH:-/mnt/user/appdata/nbaautoreport/data}"
mkdir -p "$DATA_HOST"

cd "$REPO"
git pull

# Update API (mounts the shared data folder and reads precomputed JSON from it)
docker build -f Dockerfile -t nbaautoreport .
docker stop nbaautoreport || true
docker rm nbaautoreport || true
docker run -d --name nbaautoreport --restart unless-stopped \
  -p 8000:8000 \
  -v "$DATA_HOST":/app/data \
  -e DATA_DIR=/app/data \
  nbaautoreport

# Update Streamlit
docker build -f Dockerfile.streamlit -t nbastats .
docker stop nbastats || true
docker rm nbastats || true
docker run -d --name nbastats --restart unless-stopped -p 8501:8501 nbastats

# Refresh the precomputed data so a fresh deploy has data immediately
docker exec -e DATA_DIR=/app/data -e PYTHONPATH=/app -w /app nbaautoreport python scripts/precompute.py

echo "All containers updated and restarted"

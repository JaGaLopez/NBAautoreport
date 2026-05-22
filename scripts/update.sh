#!/bin/bash
set -e

cd /mnt/user/websites/NBAautoreport
git pull

# Update API
docker build -f Dockerfile -t nbaautoreport .
docker stop nbaautoreport || true
docker rm nbaautoreport || true
docker run -d --name nbaautoreport --restart unless-stopped -p 8000:8000 nbaautoreport

# Update Streamlit
docker build -f Dockerfile.streamlit -t nbastats .
docker stop nbastats || true
docker rm nbastats || true
docker run -d --name nbastats --restart unless-stopped -p 8501:8501 nbastats

echo "All containers updated and restarted"

#!/bin/bash
# Re-run all nba_api calls + computation and refresh the precomputed JSON.
# Schedule this DAILY via the Unraid User Scripts plugin.
# The API serves the existing files the whole time, so there is zero downtime.
set -e

docker exec -e DATA_DIR=/app/data -e PYTHONPATH=/app -w /app nbaautoreport python scripts/precompute.py
echo "NBA data refreshed: $(date)"

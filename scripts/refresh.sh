#!/usr/bin/env bash
#
# Manual data refresh, for when you don't want to go through GitHub Actions.
#
#   ./refresh.sh                        refresh whatever is stale, in background
#   ./refresh.sh --follow               same, but stream the log until it ends
#   ./refresh.sh --force shooting       rebuild these datasets even if current
#   ./refresh.sh --force effort profiles --follow
#
# Precompute skips any dataset whose stored file already matches the current
# schema, so a plain run does nothing when nothing has changed. --force deletes
# the named files first, which is what makes it recompute them.
#
# Always creates a NEW container from the current image: `docker start` on an
# old one replays whatever code that container was built with, which is the
# usual reason a "refresh" appears to do nothing after a deploy.
set -euo pipefail

DATA_HOST=${DATA_HOST:-/mnt/user/appdata/nbaautoreport/data}
IMAGE=${IMAGE:-nbaautoreport}
NAME=${NAME:-nbarefresh}
SEASONS=${SEASONS:-"2024-25 2023-24 2022-23 2021-22"}

follow=false
force=()

while [ $# -gt 0 ]; do
    case "$1" in
        --follow|-f) follow=true; shift ;;
        --force) shift
                 # everything up to the next flag is a dataset name
                 while [ $# -gt 0 ] && [[ "$1" != --* ]]; do force+=("$1"); shift; done ;;
        --help|-h) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

# Refuse to start a second crawl over the same files. Two precomputes writing
# the same JSON race on the .tmp rename and one of them fails.
if docker ps --filter "name=^/${NAME}$" --filter "status=running" --format '{{.Names}}' | grep -q .; then
    echo "A refresh is already running. Watch it with: docker logs -f ${NAME}"
    exit 1
fi

if [ ${#force[@]} -gt 0 ]; then
    for kind in "${force[@]}"; do
        for season in $SEASONS; do
            target="${DATA_HOST}/${season}_${kind}.json"
            [ -f "$target" ] && rm -f "$target" && echo "removed ${season}_${kind}.json"
        done
    done
fi

docker rm -f "$NAME" >/dev/null 2>&1 || true
mkdir -p "$DATA_HOST"

docker run -d --name "$NAME" \
    -v "$DATA_HOST":/app/data \
    -e DATA_DIR=/app/data -e PYTHONPATH=/app -e PYTHONUNBUFFERED=1 -w /app \
    "$IMAGE" python -u scripts/precompute.py >/dev/null

echo "Refresh started. Follow it with: docker logs -f ${NAME}"
$follow && exec docker logs -f "$NAME"

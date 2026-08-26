"""
Fetch all nba_api data and run all computation once, writing the results to
DATA_DIR as JSON. Intended to run once per day on the server. The FastAPI app
then serves these files instead of hitting nba_api live on every request.

Run from the repo root with the package importable, e.g.:
    PYTHONPATH=/app DATA_DIR=/app/data python scripts/precompute.py
"""
import os
import sys
import json
import time

# Ensure the repo root is importable when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics.GetTeamStats import GetTeamStats
from analytics.GetAdvancedTeamStats import GetAdvancedTeamStats
from analytics.BuildAverageTeam import BuildAverageTeam
from analytics.GetWeeklyNetRating import GetWeeklyNetRating
from analytics.GetEffortWhileLosing import GetEffortWhileLosing
from analytics.GetShootingVariance import GetShootingVariance, SCHEMA as SHOOTING_SCHEMA
from analytics.GetThreePointVariance import GetThreePointVariance, SCHEMA as THREEPOINT_SCHEMA
from analytics.LineScores import iter_line_scores
from analytics import GetQ4Comebacks as comebacks
from analytics import GetHotStarts as hotstarts
from analytics.GetHotStarts import SCHEMA as HOTSTARTS_SCHEMA

SEASONS = ["2024-25", "2023-24", "2022-23", "2021-22"]
DATA_DIR = os.environ.get("DATA_DIR", "data")

# A regular season is complete once every team has played all 82 games.
# (Playoffs are out of scope for now.)
GAMES_IN_SEASON = 82
TEAMS_IN_LEAGUE = 30


def _write(filename, obj):
    path = os.path.join(DATA_DIR, filename)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)  # atomic swap so the API never reads a half-written file
    print(f"  wrote {filename}")


def _season_complete(season):
    """True if stored data shows all 30 teams have played 82 games, no API call."""
    path = os.path.join(DATA_DIR, f"{season}_basic.json")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        rows = json.load(f)
    return (
        len(rows) >= TEAMS_IN_LEAGUE
        and all(row.get("GP", 0) >= GAMES_IN_SEASON for row in rows)
    )


# Datasets whose stored shape is versioned. A finished season is normally left
# alone once written, so without this a stat that gains a field would never
# regenerate for any completed season.
DATASET_SCHEMA = {
    "shooting": SHOOTING_SCHEMA,
    "threepoint": THREEPOINT_SCHEMA,
    "hotstarts": HOTSTARTS_SCHEMA,
    # Comebacks deliberately has no schema. Its stored files are valid and cost
    # a full crawl to rebuild, so it keeps the older league_average check below.
}


def _core_current(season, kind):
    """True if a stored core dataset exists and is not an outdated shape."""
    path = os.path.join(DATA_DIR, f"{season}_{kind}.json")
    if not os.path.exists(path):
        return False

    want = DATASET_SCHEMA.get(kind)
    if want is None:
        return True

    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return False
    return isinstance(data, dict) and data.get("schema") == want


def _crawl_current(season, kind):
    """True if a stored crawl file is usable as-is.

    Versioned datasets are checked by schema. The rest just need the
    {league_average, teams} shape: older comeback files were a plain team-keyed
    dict and must be regenerated so the UI can read league_average.
    """
    path = os.path.join(DATA_DIR, f"{season}_{kind}.json")
    if not os.path.exists(path):
        return False

    if kind in DATASET_SCHEMA:
        return _core_current(season, kind)

    with open(path) as f:
        data = json.load(f)
    return isinstance(data, dict) and "league_average" in data


# Cheap "core" datasets: a few quick nba_api calls each.
CORE_DATASETS = (
    ("basic",         lambda s: GetTeamStats(s).to_dict(orient="records")),
    ("advanced",      lambda s: GetAdvancedTeamStats(s).to_dict(orient="records")),
    ("average",       lambda s: BuildAverageTeam(s).to_dict()),
    ("weekly_netrtg", lambda s: GetWeeklyNetRating(s)),
    # Four league-wide calls (hustle + advanced, split W/L), cheap enough for
    # the core pass, unlike the per-game comebacks work below.
    ("effort",        lambda s: GetEffortWhileLosing(s)),
    # One game-log call for the whole league plus two shot-tracking calls.
    ("shooting",      lambda s: GetShootingVariance(s)),
    # Same three calls again, from behind the arc only.
    ("threepoint",    lambda s: GetThreePointVariance(s)),
)

# Datasets built from the season's line scores. They share a single crawl
# (~1,200 throttled calls, the better part of an hour), so adding another stat
# here costs computation but no extra API calls.
CRAWL_DATASETS = (
    ("comebacks", comebacks),
    ("hotstarts", hotstarts),
)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # The image's nba_api version, printed because it is the usual suspect when
    # a stat works locally but fails on the server: the pip layer is cached
    # until requirements.txt changes, so a rebuilt image can still carry an old
    # nba_api with different endpoint names or parameters.
    try:
        from importlib.metadata import version
        print(f"nba_api {version('nba_api')}")
    except Exception as e:
        print(f"could not read nba_api version: {e}")

    # Pass 1, cheap core datasets for EVERY season first. These are a handful
    # of quick calls each, so the whole pass finishes fast. Doing them all up
    # front means that if the expensive comebacks pass below is interrupted
    # (throttling, or a redeploy restarting the run), every season still has the
    # stats the dashboard needs instead of only the first one processed.
    for season in SEASONS:
        complete = _season_complete(season)
        for kind, compute in CORE_DATASETS:
            # In-progress seasons change daily (recompute); finished seasons only
            # need a file that's actually missing.
            if not complete or not _core_current(season, kind):
                print(f"Computing {season} {kind}...")
                # Isolated per dataset. Without this, one failing stat aborts
                # the whole refresh, including the line score crawl below, and
                # every other season silently goes stale.
                try:
                    _write(f"{season}_{kind}.json", compute(season))
                except Exception as e:
                    print(f"  WARNING: {kind} failed for {season}: {e}")
                time.sleep(1)

    # Pass 2, the expensive, network-fragile line score crawl. One walk over the
    # season feeds every stat built on it, so the cost is the same whether one
    # dataset is missing or all of them are. Isolated per season so a throttled
    # failure on one doesn't starve the rest.
    for season in SEASONS:
        complete = _season_complete(season)
        # Skip only a finished season whose datasets are all already stored in
        # the current {league_average, teams} shape. Older comeback files were
        # a plain team-keyed dict and must be regenerated.
        pending = [
            (kind, module) for kind, module in CRAWL_DATASETS
            if not (complete and _crawl_current(season, kind))
        ]
        if not pending:
            continue

        print(f"Computing {season} {', '.join(k for k, _ in pending)}...")
        try:
            tallies = [(kind, module, module.new_tally()) for kind, module in pending]
            for game_id, line_score in iter_line_scores(season):
                for _, module, tally in tallies:
                    module.add_game(tally, game_id, line_score)
            for kind, module, tally in tallies:
                _write(f"{season}_{kind}.json", module.finish(tally))
        except Exception as e:
            print(f"  WARNING: line score crawl failed for {season}: {e}")
        time.sleep(1)

    print(f"Done. Data dir: {DATA_DIR}")


if __name__ == "__main__":
    main()

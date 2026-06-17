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
from analytics.GetQ4Comebacks import GetAllTeamsQ4Comebacks

SEASONS = ["2024-25", "2023-24", "2022-23", "2021-22"]
DATA_DIR = os.environ.get("DATA_DIR", "data")

# A regular season is complete once every team has played all 82 games.
# (Playoffs are out of scope for now.)
GAMES_IN_SEASON = 82
TEAMS_IN_LEAGUE = 30

# Every JSON file a fully-processed season should have
KINDS = ("basic", "advanced", "average", "weekly_netrtg", "comebacks")


def _write(filename, obj):
    path = os.path.join(DATA_DIR, filename)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)  # atomic swap so the API never reads a half-written file
    print(f"  wrote {filename}")


def _season_complete(season):
    """True if stored data shows all 30 teams have played 82 games — no API call."""
    path = os.path.join(DATA_DIR, f"{season}_basic.json")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        rows = json.load(f)
    return (
        len(rows) >= TEAMS_IN_LEAGUE
        and all(row.get("GP", 0) >= GAMES_IN_SEASON for row in rows)
    )


def _has_all_files(season):
    return all(
        os.path.exists(os.path.join(DATA_DIR, f"{season}_{kind}.json"))
        for kind in KINDS
    )


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    for season in SEASONS:
        # Skip finished seasons only if every file is already stored (so new
        # datasets like weekly net rating get backfilled once for old seasons).
        if _season_complete(season) and _has_all_files(season):
            print(f"Skipping {season} (all 82 games played, already stored)")
            continue

        print(f"Processing {season}...")

        basic = GetTeamStats(season)
        time.sleep(1)
        advanced = GetAdvancedTeamStats(season)
        time.sleep(1)
        average = BuildAverageTeam(season)
        time.sleep(1)
        weekly = GetWeeklyNetRating(season)
        time.sleep(1)
        # Expensive: one game-log call per team plus one box score per game.
        comebacks = GetAllTeamsQ4Comebacks(season)
        time.sleep(1)

        _write(f"{season}_basic.json", basic.to_dict(orient="records"))
        _write(f"{season}_advanced.json", advanced.to_dict(orient="records"))
        _write(f"{season}_average.json", average.to_dict())
        _write(f"{season}_weekly_netrtg.json", weekly)
        _write(f"{season}_comebacks.json", comebacks)

    print(f"Done. Data dir: {DATA_DIR}")


if __name__ == "__main__":
    main()

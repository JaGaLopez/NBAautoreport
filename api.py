import os
import json
from fastapi import FastAPI
from analytics.BuildAverageTeam import BuildAverageTeam
from analytics.GetTeamStats import GetTeamStats
from analytics.GetAdvancedTeamStats import GetAdvancedTeamStats

app = FastAPI()

DATA_DIR = os.environ.get("DATA_DIR", "data")


def _cached(filename):
    """Return precomputed JSON if it exists, else None."""
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


@app.get("/average-team/{season}")
def average_team(season: str):
    cached = _cached(f"{season}_average.json")
    if cached is not None:
        return cached
    return BuildAverageTeam(season).to_dict()


@app.get("/teams/{season}/advanced")
def teams_advanced(season: str):
    cached = _cached(f"{season}_advanced.json")
    if cached is not None:
        return cached
    return GetAdvancedTeamStats(season).to_dict(orient="records")


@app.get("/teams/{season}")
def teams(season: str):
    cached = _cached(f"{season}_basic.json")
    if cached is not None:
        return cached
    return GetTeamStats(season).to_dict(orient="records")

import os
import json
from fastapi import FastAPI, HTTPException

app = FastAPI()

DATA_DIR = os.environ.get("DATA_DIR", "data")

# This API never calls nba_api directly. All nba_api access happens once per day
# in scripts/precompute.py, which writes the JSON files served here. If a file is
# missing, the data simply hasn't been precomputed yet.


def _cached(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=503, detail=f"{filename} has not been precomputed yet")
    with open(path) as f:
        return json.load(f)


@app.get("/average-team/{season}")
def average_team(season: str):
    return _cached(f"{season}_average.json")


@app.get("/teams/{season}/advanced")
def teams_advanced(season: str):
    return _cached(f"{season}_advanced.json")


@app.get("/teams/{season}/weekly-netrating")
def teams_weekly_netrating(season: str):
    return _cached(f"{season}_weekly_netrtg.json")


@app.get("/teams/{season}/comebacks")
def teams_comebacks(season: str):
    return _cached(f"{season}_comebacks.json")


@app.get("/teams/{season}/effort-while-losing")
def teams_effort_while_losing(season: str):
    return _cached(f"{season}_effort.json")


@app.get("/teams/{season}/hot-starts")
def teams_hot_starts(season: str):
    return _cached(f"{season}_hotstarts.json")


@app.get("/teams/{season}/shooting-variance")
def teams_shooting_variance(season: str):
    return _cached(f"{season}_shooting.json")


@app.get("/teams/{season}")
def teams(season: str):
    return _cached(f"{season}_basic.json")

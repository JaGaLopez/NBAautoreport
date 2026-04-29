from fastapi import FastAPI
from analytics.BuildAverageTeam import BuildAverageTeam
from analytics.GetTeamStats import GetTeamStats

app = FastAPI()

@app.get("/average-team/{season}")
def average_team(season: str):
    data = BuildAverageTeam(season)
    return data.to_dict()

@app.get("/teams/{season}")
def teams(season: str):
    data = GetTeamStats(season)
    return data.to_dict(orient="records")
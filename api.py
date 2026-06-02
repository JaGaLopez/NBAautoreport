from fastapi import FastAPI
from analytics.BuildAverageTeam import BuildAverageTeam
from analytics.GetTeamStats import GetTeamStats
from analytics.GetAdvancedTeamStats import GetAdvancedTeamStats

app = FastAPI()

@app.get("/average-team/{season}")
def average_team(season: str):
    data = BuildAverageTeam(season)
    return data.to_dict()

@app.get("/teams/{season}/advanced")
def teams_advanced(season: str):
    data = GetAdvancedTeamStats(season)
    return data.to_dict(orient="records")

@app.get("/teams/{season}")
def teams(season: str):
    data = GetTeamStats(season)
    return data.to_dict(orient="records")
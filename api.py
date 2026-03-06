from fastapi import FastAPI
from BuildAverageTeam import BuildAverageTeam

app = FastAPI()

@app.get("/average-team/{season}")
def average_team(season: str):
    data = BuildAverageTeam(season)
    return data.to_dict()
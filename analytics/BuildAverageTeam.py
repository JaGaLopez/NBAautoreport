import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import sklearn as sk
from nba_api.stats.endpoints import leaguedashteamstats as teamstats

def BuildAverageTeam(SEASON):
    SEASON_TYPE = "Regular Season"
    PER_MODE = "PerGame"   # use the same mode for both tables

    base_df = teamstats.LeagueDashTeamStats(
        season=SEASON,
        season_type_all_star=SEASON_TYPE,
        per_mode_detailed=PER_MODE,
        measure_type_detailed_defense="Base",
    ).get_data_frames()[0]

    adv_df = teamstats.LeagueDashTeamStats(
        season=SEASON,
        season_type_all_star=SEASON_TYPE,
        per_mode_detailed=PER_MODE,
        measure_type_detailed_defense="Advanced"
    ).get_data_frames()[0]

    adv_keep = [
        "TEAM_ID",
        "TEAM_NAME",
        "TS_PCT", 
        "AST_PCT", 
        "OREB_PCT", 
        "DREB_PCT", 
        "REB_PCT", 
        "TM_TOV_PCT"
    ]
    adv_df = adv_df[adv_keep]

    df = base_df.merge(adv_df, on=["TEAM_ID", "TEAM_NAME"], how="left")

    df["2P"] = df["FGM"] - df["FG3M"]
    df["2PA"] = df["FGA"] - df["FG3A"]
    df["2P%"] = np.where(df["2PA"] > 0, df["2P"] / df["2PA"], np.nan)

    df["3PAr"] = np.where(df["FGA"] > 0, df["FG3A"] / df["FGA"], np.nan)
    df["FTr"] = np.where(df["FGA"] > 0, df["FTA"] / df["FGA"], np.nan)

    df = df.rename(columns={
        "FGM": "FG",
        "FGA": "FGA",
        "FG_PCT": "FG%",
        "FG3M": "3P",
        "FG3A": "3PA",
        "FG3_PCT": "3P%",
        "FTM": "FT",
        "FTA": "FTA",
        "FT_PCT": "FT%",
        "OREB": "ORB",
        "DREB": "DRB",
        "REB": "TRB",
        "AST": "AST",
        "STL": "STL",
        "BLK": "BLK",
        "TOV": "TOV",
        "PF": "PF",
        "PTS": "PTS",
        "TS_PCT": "TS%",
        "OREB_PCT": "ORB%",
        "DREB_PCT": "DRB%",
        "REB_PCT": "TRB%",
        "AST_PCT": "AST%",
        "TM_TOV_PCT": "TOV%"
    })

    desired_cols = [
        "FG", "FGA", "FG%",
        "3P", "3PA", "3P%",
        "2P", "2PA", "2P%",
        "FT", "FTA", "FT%",
        "ORB", "DRB", "TRB",
        "AST", "STL", "BLK", "TOV", "PF", "PTS",
        "TS%", "3PAr", "FTr",
        "ORB%", "DRB%", "TRB%", "AST%", "TOV%"
    ]

    averageteam = df[desired_cols].mean(numeric_only=True).round(2)

    return averageteam


import pandas as pd
from nba_api.stats.endpoints import leaguedashteamstats as teamstats

def GetAdvancedTeamStats(SEASON):
    SEASON_TYPE = "Regular Season"

    df = teamstats.LeagueDashTeamStats(
        season=SEASON,
        season_type_all_star=SEASON_TYPE,
        per_mode_detailed="PerGame",
        measure_type_detailed_defense="Advanced",
    ).get_data_frames()[0]

    return df

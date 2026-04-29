import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import sklearn as sk
from nba_api.stats.endpoints import leaguedashteamstats as teamstats
from scipy.stats import percentileofscore

def CompareAllTeams(SEASON):

    SEASON_TYPE = "Regular Season"

    
    df = teamstats.LeagueDashTeamStats(
        season=SEASON,
        season_type_all_star=SEASON_TYPE,
        per_mode_detailed="PerGame",
        measure_type_detailed_defense="Base",
    ).get_data_frames()[0]

    return df

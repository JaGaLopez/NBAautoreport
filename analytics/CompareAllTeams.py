import pandas as pd
from scipy.stats import percentileofscore
from nba_api.stats.endpoints import leaguedashteamstats as teamstats
from analytics.BuildAverageTeam import BuildAverageTeam


def CompareAllTeams(SEASON):

    SEASON_TYPE = "Regular Season"

    # Pull team stats (same data source BuildAverageTeam used)
    df = teamstats.LeagueDashTeamStats(
        season=SEASON,
        season_type_all_star=SEASON_TYPE,
        per_mode_detailed="PerGame",
        measure_type_detailed_defense="Base",
    ).get_data_frames()[0]

    # Get the average team (THIS is the key part)
    avg_team = BuildAverageTeam(SEASON)

    # Only keep stats that exist in the average output
    stat_cols = [col for col in avg_team.index if col in df.columns]

    stats_df = df[["TEAM_NAME"] + stat_cols].copy()
    league_stats = stats_df[stat_cols]

    # -----------------------
    # STANDARD DEVIATIONS FROM MEAN
    # -----------------------

    league_std = league_stats.std()

    zscore_df = (league_stats - avg_team[stat_cols]) / league_std
    zscore_df.insert(0, "TEAM_NAME", stats_df["TEAM_NAME"])
    zscore_df = zscore_df.round(2)

    # -----------------------
    # PERCENTILES
    # -----------------------

    percentile_df = pd.DataFrame()

    for col in stat_cols:
        percentile_df[col] = [
            percentileofscore(league_stats[col], value)
            for value in league_stats[col]
        ]

    percentile_df.insert(0, "TEAM_NAME", stats_df["TEAM_NAME"])
    percentile_df = percentile_df.round(2)

    return percentile_df, zscore_df

percentile_df, zscore_df = CompareAllTeams("2023-24")

print("PERCENTILES")
print(percentile_df.head())

print("\nZ SCORES")
print(zscore_df.head())
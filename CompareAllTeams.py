import pandas as pd
from scipy.stats import percentileofscore
from nba_api.stats.endpoints import leaguedashteamstats as teamstats


def CompareAllTeams(SEASON):

    SEASON_TYPE = "Regular Season"

    base_df = teamstats.LeagueDashTeamStats(
        season=SEASON,
        season_type_all_star=SEASON_TYPE,
        per_mode_detailed="PerGame",
        measure_type_detailed_defense="Base"
    ).get_data_frames()[0]

    adv_df = teamstats.LeagueDashTeamStats(
        season=SEASON,
        season_type_all_star=SEASON_TYPE,
        per_mode_detailed="PerGame",
        measure_type_detailed_defense="Advanced"
    ).get_data_frames()[0]

    df = base_df.merge(adv_df, on=["TEAM_ID", "TEAM_NAME"], how="left")

    # stats you want to compare
    desired_cols = [
        "FG", "FGA", "FG_PCT",
        "FG3M", "FG3A", "FG3_PCT",
        "FG2M", "FG2A", "FG2_PCT",
        "FTM", "FTA", "FT_PCT",
        "OREB", "DREB", "REB",
        "AST", "STL", "BLK",
        "TOV", "PF", "PTS",
        "TS_PCT", "E_OFF_RATING",
        "AST_PCT", "TOV_PCT"
    ]

    existing_cols = [c for c in desired_cols if c in df.columns]

    stats_df = df[["TEAM_NAME"] + existing_cols].copy()

    league_stats = stats_df[existing_cols]


    league_mean = league_stats.mean()
    league_std = league_stats.std()

    zscore_df = (league_stats - league_mean) / league_std
    zscore_df.insert(0, "TEAM_NAME", stats_df["TEAM_NAME"])
    zscore_df = zscore_df.round(2)


    percentile_df = pd.DataFrame()

    for col in existing_cols:
        percentile_df[col] = [
            percentileofscore(league_stats[col], value)
            for value in league_stats[col]
        ]

    percentile_df.insert(0, "TEAM_NAME", stats_df["TEAM_NAME"])
    percentile_df = percentile_df.round(2)

    return percentile_df, zscore_df

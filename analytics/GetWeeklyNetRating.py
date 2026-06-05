import pandas as pd
from nba_api.stats.endpoints import teamgamelogs


def GetWeeklyNetRating(SEASON):
    """
    Cumulative (season-to-date) net rating by week for every team, plus the
    league average by week.

    Returns a dict:
        {
            "weeks": ["2024-10-21", ...],          # Monday of each game-week, sorted
            "teams": {"Atlanta Hawks": [..], ...}, # cumulative net rtg aligned to weeks
            "league_avg": [..],                    # cumulative league avg aligned to weeks
        }
    Cumulative value at week W = mean net rating of all games played through W.
    Weeks before a team's first game are None (rendered as a gap).
    """
    df = teamgamelogs.TeamGameLogs(
        season_nullable=SEASON,
        season_type_nullable="Regular Season",
        measure_type_player_game_logs_nullable="Advanced",
    ).get_data_frames()[0]

    net_col = "NET_RATING" if "NET_RATING" in df.columns else "E_NET_RATING"
    df = df[["TEAM_NAME", "GAME_DATE", net_col]].copy()
    df = df.rename(columns={net_col: "NET_RATING"})
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])

    # Bucket each game into the Monday that starts its week
    df["WEEK"] = (
        df["GAME_DATE"] - pd.to_timedelta(df["GAME_DATE"].dt.weekday, unit="D")
    ).dt.normalize()

    weeks = sorted(df["WEEK"].unique())
    week_labels = [pd.Timestamp(w).strftime("%Y-%m-%d") for w in weeks]

    def cumulative(frame):
        out = []
        for w in weeks:
            games = frame[frame["WEEK"] <= w]["NET_RATING"]
            out.append(round(float(games.mean()), 2) if len(games) else None)
        return out

    teams = {team: cumulative(tdf) for team, tdf in df.groupby("TEAM_NAME")}
    league_avg = cumulative(df)

    return {"weeks": week_labels, "teams": teams, "league_avg": league_avg}

import pandas as pd
from nba_api.stats.endpoints import teamgamelogs

# Bumped to 2 when the weekly payload gained per-week offensive and defensive
# ratings alongside the net rating it already carried.
SCHEMA = 2


def GetWeeklyNetRating(SEASON):
    """
    Cumulative (season-to-date) ratings by week for every team, plus the
    league average by week.

    Returns a dict:
        {
            "schema": 2,
            "weeks": ["2024-10-21", ...],          # Monday of each game-week, sorted
            "teams": {"Atlanta Hawks": [..], ...}, # cumulative net rtg aligned to weeks
            "league_avg": [..],                    # cumulative league avg aligned to weeks
            "ortg": {"Atlanta Hawks": [..], ...},  # same alignment, offensive rating
            "drtg": {"Atlanta Hawks": [..], ...},  # same alignment, defensive rating
        }
    Cumulative value at week W = mean rating of all games played through W.
    Weeks before a team's first game are None (rendered as a gap).

    "teams" stays net-only so the weekly trend chart reads it unchanged; the
    two rating series are separate keys rather than a reshaped payload.
    """
    df = teamgamelogs.TeamGameLogs(
        season_nullable=SEASON,
        season_type_nullable="Regular Season",
        measure_type_player_game_logs_nullable="Advanced",
    ).get_data_frames()[0]

    # One call carries all three ratings, so the offensive and defensive series
    # cost nothing beyond the net rating this module already fetched.
    cols = {}
    for name, fallback in (("NET_RATING", "E_NET_RATING"),
                           ("OFF_RATING", "E_OFF_RATING"),
                           ("DEF_RATING", "E_DEF_RATING")):
        cols[name] = name if name in df.columns else fallback

    df = df[["TEAM_NAME", "GAME_DATE"] + list(cols.values())].copy()
    df = df.rename(columns={v: k for k, v in cols.items()})
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])

    # Bucket each game into the Monday that starts its week
    df["WEEK"] = (
        df["GAME_DATE"] - pd.to_timedelta(df["GAME_DATE"].dt.weekday, unit="D")
    ).dt.normalize()

    weeks = sorted(df["WEEK"].unique())
    week_labels = [pd.Timestamp(w).strftime("%Y-%m-%d") for w in weeks]

    def cumulative(frame, col):
        out = []
        for w in weeks:
            games = frame[frame["WEEK"] <= w][col]
            out.append(round(float(games.mean()), 2) if len(games) else None)
        return out

    by_team = list(df.groupby("TEAM_NAME"))
    return {
        "schema": SCHEMA,
        "weeks": week_labels,
        "teams": {team: cumulative(t, "NET_RATING") for team, t in by_team},
        "league_avg": cumulative(df, "NET_RATING"),
        "ortg": {team: cumulative(t, "OFF_RATING") for team, t in by_team},
        "drtg": {team: cumulative(t, "DEF_RATING") for team, t in by_team},
    }

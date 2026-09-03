"""Three-point shooting: how much a team shoots from deep, how well, and who.

An overview rather than a single number. Three questions, in order:

    Volume    how many threes they take, and what share of their shots that is
    Accuracy  what they hit, against the league and against last season
    Who       the shooters actually taking them, and how streaky each one is

The season-over-season half matters because three-point volume is the fastest
moving thing in the league: a team taking 40 a game is unremarkable now and
would have led the league a decade ago. Comparing a team to its own prior
season says more about intent than comparing it to a league average that keeps
sliding.

Cheap: three league-wide calls, no per-game crawl.
"""
import pandas as pd

from analytics.GetShootingVariance import (
    _fetch_game_logs,
    _percentiles,
    _retry,
    _TIMEOUT,
)
from nba_api.stats.endpoints import playergamelogs

# Bump whenever the stored shape changes, so precompute regenerates a finished
# season's file instead of leaving a stale one in place.
SCHEMA = 2

# A player needs this many attempts across the season before their percentage
# is worth showing. Below it, a bench player who went 4-for-6 in garbage time
# outranks everyone.
MIN_PLAYER_ATTEMPTS = 100

# How many shooters to list per team.
SHOOTERS_SHOWN = 4

# A team game with almost no attempts from deep would swing the game-to-game
# spread on noise alone.
MIN_TEAM_ATTEMPTS = 5


def _prior_season(season):
    """'2024-25' -> '2023-24'. None if the string isn't a season."""
    try:
        start = int(season[:4])
    except (TypeError, ValueError):
        return None
    return f"{start - 1}-{str(start)[2:]}"


def _fetch_player_logs(season, season_type):
    return _retry(
        lambda: playergamelogs.PlayerGameLogs(
            season_nullable=season,
            season_type_nullable=season_type,
            timeout=_TIMEOUT,
        ).get_data_frames()[0]
    )


def _team_frame(logs):
    """Team game logs reduced to the three-point columns, typed and cleaned."""
    needed = ("TEAM_NAME", "GAME_DATE", "FGA", "FG3M", "FG3A")
    if logs is None or logs.empty or any(c not in logs.columns for c in needed):
        return None

    df = logs[list(needed)].copy()
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
    for col in ("FGA", "FG3M", "FG3A"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["FG3A"])
    return df[df["FG3A"] >= MIN_TEAM_ATTEMPTS]


def _team_totals(df):
    """Season three-point aggregates for every team in a game-log frame."""
    out = {}
    for team, games in df.groupby("TEAM_NAME"):
        played = len(games)
        fg3a, fg3m = float(games["FG3A"].sum()), float(games["FG3M"].sum())
        fga = float(games["FGA"].sum())
        if not fg3a or not fga:
            continue

        per_game = games["FG3M"] / games["FG3A"]
        out[team] = {
            "games": played,
            "fg3a": fg3a / played,
            "fg3m": fg3m / played,
            "fg3_pct": fg3m / fg3a,
            # Share of all field goal attempts taken from three.
            "fg3a_rate": fg3a / fga,
            "fg3_stdev": float(per_game.std()) if played > 1 else None,
        }
    return out


def _shooters(player_logs):
    """The most accurate high-volume shooters on each team, with their spread.

    A player is credited to the team he appears for most often, so a midseason
    trade lands him with whoever he actually shot for.
    """
    needed = ("PLAYER_NAME", "TEAM_NAME", "FG3M", "FG3A")
    if player_logs is None or player_logs.empty:
        return {}
    if any(c not in player_logs.columns for c in needed):
        return {}

    df = player_logs[list(needed)].copy()
    for col in ("FG3M", "FG3A"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["FG3A"])

    by_team = {}
    for (name, team), games in df.groupby(["PLAYER_NAME", "TEAM_NAME"]):
        fg3a, fg3m = float(games["FG3A"].sum()), float(games["FG3M"].sum())
        if fg3a < MIN_PLAYER_ATTEMPTS:
            continue

        played = len(games)
        makes = games["FG3M"]
        by_team.setdefault(team, []).append({
            "name": name,
            "games": played,
            "fg3a": round(fg3a / played, 1),
            "fg3m": round(fg3m / played, 1),
            "fg3_pct": round(fg3m / fg3a, 3),
            # Spread in makes per night, which reads more plainly than the
            # spread of a percentage taken over five or six attempts.
            "fg3m_stdev": round(float(makes.std()), 1) if played > 1 else None,
            # Share of games he made none at all: the concrete version of cold.
            "blank_pct": round(float((makes == 0).mean()), 3),
        })

    for team, players in by_team.items():
        players.sort(key=lambda p: -p["fg3_pct"])
        by_team[team] = players[:SHOOTERS_SHOWN]
    return by_team


def GetThreePointShooting(SEASON, SEASON_TYPE="Regular Season"):
    """Three-point overview for every team in a season.

    Returns:
        {
            "schema": 2,
            "league_average": 37.6,      # league mean 3PA per game
            "league": {"fg3a": 37.6, "fg3_pct": 0.36, "fg3a_rate": 0.42},
            "prior_season": "2023-24",   # None if it couldn't be fetched
            "as_of": "2025-04-13",
            "teams": {
                "Boston Celtics": {
                    "games": 82,
                    "fg3a": 48.2, "fg3m": 17.8, "fg3_pct": 0.368,
                    "fg3a_rate": 0.535,
                    "fg3a_percentile": 100, "fg3_pct_percentile": 72,
                    "fg3_stdev": 7.0,        # game-to-game, in points
                    "prior": {"fg3a": 42.5, "fg3_pct": 0.383, "fg3a_rate": 0.47},
                    "change": {"fg3a": 5.7, "fg3_pct_pts": -1.5,
                               "fg3a_rate_pts": 6.5},
                    "shooters": [
                        {"name": "...", "games": 70, "fg3a": 8.0, "fg3m": 3.1,
                         "fg3_pct": 0.388, "fg3m_stdev": 1.9, "blank_pct": 0.04},
                        ...
                    ],
                },
                ...
            },
        }

    `prior` and `change` are omitted for a team with no prior-season data, which
    covers the first stored season and any expansion team. An empty `teams`
    dict means the game logs couldn't be fetched; callers should treat that as
    "skip this stat", not as an error.
    """
    empty = {
        "schema": SCHEMA,
        "league_average": 0,
        "league": {},
        "prior_season": None,
        "as_of": None,
        "teams": {},
    }

    current = _team_frame(_fetch_game_logs(SEASON, SEASON_TYPE))
    if current is None or current.empty:
        return empty

    totals = _team_totals(current)
    if not totals:
        return empty

    prior_season = _prior_season(SEASON)
    prior_frame = _team_frame(_fetch_game_logs(prior_season, SEASON_TYPE)) if prior_season else None
    prior_totals = _team_totals(prior_frame) if prior_frame is not None else {}

    shooters = _shooters(_fetch_player_logs(SEASON, SEASON_TYPE))

    volume_ranks = _percentiles([t["fg3a"] for t in totals.values()])
    pct_ranks = _percentiles([t["fg3_pct"] for t in totals.values()])

    teams = {}
    for name, t in totals.items():
        entry = {
            "games": t["games"],
            "fg3a": round(t["fg3a"], 1),
            "fg3m": round(t["fg3m"], 1),
            "fg3_pct": round(t["fg3_pct"], 3),
            "fg3a_rate": round(t["fg3a_rate"], 3),
            "fg3a_percentile": volume_ranks.get(t["fg3a"]),
            "fg3_pct_percentile": pct_ranks.get(t["fg3_pct"]),
            "fg3_stdev": round(t["fg3_stdev"] * 100, 1) if t["fg3_stdev"] is not None else None,
            "shooters": shooters.get(name, []),
        }

        was = prior_totals.get(name)
        if was:
            entry["prior"] = {
                "fg3a": round(was["fg3a"], 1),
                "fg3_pct": round(was["fg3_pct"], 3),
                "fg3a_rate": round(was["fg3a_rate"], 3),
            }
            entry["change"] = {
                "fg3a": round(t["fg3a"] - was["fg3a"], 1),
                "fg3_pct_pts": round((t["fg3_pct"] - was["fg3_pct"]) * 100, 1),
                "fg3a_rate_pts": round((t["fg3a_rate"] - was["fg3a_rate"]) * 100, 1),
            }
        teams[name] = entry

    def _mean(key):
        vals = [t[key] for t in totals.values()]
        return sum(vals) / len(vals)

    return {
        "schema": SCHEMA,
        "league_average": round(_mean("fg3a"), 1),
        "league": {
            "fg3a": round(_mean("fg3a"), 1),
            "fg3_pct": round(_mean("fg3_pct"), 3),
            "fg3a_rate": round(_mean("fg3a_rate"), 3),
        },
        "prior_season": prior_season if prior_totals else None,
        "as_of": current["GAME_DATE"].max().strftime("%Y-%m-%d"),
        "teams": teams,
    }


# Guard so importing this module never triggers nba_api calls.
# All nba_api access must go through the daily precompute (scripts/precompute.py).
if __name__ == "__main__":
    result = GetThreePointShooting("2024-25")

    league = result["league"]
    print(f"League: {league['fg3a']} 3PA per game at {league['fg3_pct']:.1%}, "
          f"{league['fg3a_rate']:.0%} of all shots\n")

    ranked = sorted(
        result["teams"].items(), key=lambda kv: -kv[1]["fg3a"]
    )
    for name, t in ranked[:5]:
        change = t.get("change", {})
        shooter = (t["shooters"] or [{}])[0]
        print(
            f"{name:<24} {t['fg3a']:>5.1f} 3PA  {t['fg3_pct']:.1%}  "
            f"({change.get('fg3a', 0):+.1f} vs last year)  "
            f"best: {shooter.get('name', 'n/a')}"
        )

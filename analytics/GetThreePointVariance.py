"""Three-point variance: the same question as shooting variance, from deep only.

Threes are where night-to-night noise actually lives. A team's overall eFG% is
anchored by layups and free-throw-line work that barely move, so a cold shooting
week is usually a cold three-point week wearing a disguise. Measuring the arc on
its own says how much of a team's swing is the part that swings.

Structure mirrors GetShootingVariance: a season baseline (accuracy, volume, and
how many of those looks are uncontested), then the last one, two, and three
weeks measured against it in the team's own standard errors.

Cheap: three league-wide calls, no per-game crawl.
"""
import time
import pandas as pd

from analytics.GetShootingVariance import (
    OPEN_RANGES,
    WINDOWS,
    _TIMEOUT,
    _fetch_game_logs,
    _percentiles,
    _retry,
    _streaks,
    _swings,
)
from nba_api.stats.endpoints import leaguedashteamptshot

# Bump whenever the stored shape changes, so precompute regenerates a finished
# season's file instead of leaving a stale one in place.
SCHEMA = 1

# A game with almost no attempts from deep would produce a wild percentage on
# noise alone, so it is left out of the game-to-game spread.
MIN_ATTEMPTS = 5


def _fetch_open_threes(season, season_type):
    """Three-point makes and attempts on open plus wide-open looks, by TEAM_ID.

    Returns {} if the tracking calls fail, which drops the shot-quality half of
    the baseline instead of failing the whole stat.
    """
    totals = {}
    for dist in OPEN_RANGES:
        df = _retry(
            lambda dist=dist: leaguedashteamptshot.LeagueDashTeamPtShot(
                season=season,
                season_type_all_star=season_type,
                close_def_dist_range_nullable=dist,
                timeout=_TIMEOUT,
            ).get_data_frames()[0]
        )
        if df is None or "TEAM_ID" not in df.columns or "FG3A" not in df.columns:
            return {}

        time.sleep(1)
        for _, row in df.iterrows():
            entry = totals.setdefault(row["TEAM_ID"], {"fg3a": 0.0, "fg3m": 0.0})
            entry["fg3a"] += float(row.get("FG3A") or 0)
            entry["fg3m"] += float(row.get("FG3M") or 0)
    return totals


def _pct(made, attempted):
    """Shooting percentage as a plain float, or None with no attempts."""
    if not attempted:
        return None
    return float(made / attempted)


def GetThreePointVariance(SEASON, SEASON_TYPE="Regular Season"):
    """Three-point baseline plus recent-form windows for every team in a season.

    Returns:
        {
            "schema": 1,
            "league_average": 7.9,   # mean fg3_stdev across teams, in points
            "league_fg3_pct": 0.36,
            "windows": ["1 Week", "2 Weeks", "3 Weeks"],
            "as_of": "2025-04-13",
            "teams": {
                "Atlanta Hawks": {
                    "fg3_stdev": 8.4,        # game-to-game swing, in points
                    "baseline": {
                        "fg3_pct": 0.363,
                        "fg3_percentile": 61,
                        "fg3m": 13.4,        # per game
                        "fg3m_stdev": 4.1,
                        "fg3a": 37.1,        # per game
                        "open_share": 0.78,  # share of threes uncontested
                        "open_share_percentile": 55,
                        "open_fg3_pct": 0.381,
                    },
                    "windows": {
                        "1 Week": {"games": 3, "fg3_pct": 0.312,
                                   "fg3_delta_pts": -5.1, "fg3m": 11.0,
                                   "fg3m_delta": -2.4, "fg3a": 36.0,
                                   "swings": 0.42},
                        ...
                    },
                    "streaks": {"avg_length": 1.8, "longest": 5,
                                "current_direction": "cold", "current_length": 2,
                                "repeat_pct": 0.49},
                },
                ...
            },
        }

    `swings` reuses the shooting-variance scale so the two cards read the same
    way: 1 is normal, 0 is cold, 2 is hot.

    An empty `teams` dict means the game logs couldn't be fetched. Callers
    should treat that as "skip this stat", not as an error.
    """
    empty = {
        "schema": SCHEMA,
        "league_average": 0,
        "league_fg3_pct": None,
        "windows": [],
        "as_of": None,
        "teams": {},
    }

    logs = _fetch_game_logs(SEASON, SEASON_TYPE)
    if logs is None or logs.empty:
        return empty

    needed = ("TEAM_ID", "TEAM_NAME", "GAME_DATE", "FG3M", "FG3A")
    if any(c not in logs.columns for c in needed):
        return empty

    logs = logs[list(needed)].copy()
    logs["GAME_DATE"] = pd.to_datetime(logs["GAME_DATE"])
    for col in ("FG3M", "FG3A"):
        logs[col] = pd.to_numeric(logs[col], errors="coerce")
    logs = logs.dropna(subset=["FG3A"])
    logs = logs[logs["FG3A"] >= MIN_ATTEMPTS]
    if logs.empty:
        return empty

    logs["FG3_PCT"] = logs["FG3M"] / logs["FG3A"]

    as_of = logs["GAME_DATE"].max()
    open_threes = _fetch_open_threes(SEASON, SEASON_TYPE)

    # Pass 1: per-team baselines, so league percentiles can be taken across them.
    baselines = {}
    for (team_id, team_name), games in logs.groupby(["TEAM_ID", "TEAM_NAME"]):
        played = len(games)
        fg3a, fg3m = float(games["FG3A"].sum()), float(games["FG3M"].sum())
        tracked = open_threes.get(team_id)

        baselines[team_name] = {
            "games": games,
            "played": played,
            "fg3_pct": _pct(fg3m, fg3a),
            # Sample stdev needs at least two games.
            "fg3_stdev": float(games["FG3_PCT"].std()) if played > 1 else None,
            "fg3m": fg3m / played,
            "fg3m_stdev": float(games["FG3M"].std()) if played > 1 else None,
            "fg3a": fg3a / played,
            "open_share": (tracked["fg3a"] / fg3a) if tracked and fg3a else None,
            "open_fg3_pct": (
                _pct(tracked["fg3m"], tracked["fg3a"]) if tracked else None
            ),
        }

    pct_ranks = _percentiles([b["fg3_pct"] for b in baselines.values()])
    open_ranks = _percentiles([b["open_share"] for b in baselines.values()])

    # Pass 2: recent-form windows against each team's own baseline.
    teams = {}
    for team_name, base in baselines.items():
        games = base["games"]
        stdev = base["fg3_stdev"]

        windows = {}
        for label, days in WINDOWS:
            recent = games[games["GAME_DATE"] > as_of - pd.Timedelta(days=days)]
            if recent.empty:
                continue

            played = len(recent)
            w_fg3a = float(recent["FG3A"].sum())
            w_fg3m = float(recent["FG3M"].sum())
            w_pct = _pct(w_fg3m, w_fg3a)
            if w_pct is None or base["fg3_pct"] is None:
                continue

            gap = w_pct - base["fg3_pct"]
            windows[label] = {
                "games": played,
                "fg3_pct": round(w_pct, 3),
                "fg3_delta_pts": round(gap * 100, 1),
                "fg3m": round(w_fg3m / played, 1),
                # Normalized against the team's own season average, so the
                # column reads as makes gained or lost per game.
                "fg3m_delta": round(w_fg3m / played - base["fg3m"], 1),
                "fg3a": round(w_fg3a / played, 1),
                "swings": _swings(gap, stdev),
            }

        teams[team_name] = {
            "fg3_stdev": round(stdev * 100, 1) if stdev is not None else None,
            "baseline": {
                "fg3_pct": round(base["fg3_pct"], 3) if base["fg3_pct"] is not None else None,
                "fg3_percentile": pct_ranks.get(base["fg3_pct"]),
                "fg3m": round(base["fg3m"], 1),
                "fg3m_stdev": (
                    round(base["fg3m_stdev"], 1)
                    if base["fg3m_stdev"] is not None else None
                ),
                "fg3a": round(base["fg3a"], 1),
                "open_share": round(base["open_share"], 3) if base["open_share"] is not None else None,
                "open_share_percentile": open_ranks.get(base["open_share"]),
                "open_fg3_pct": (
                    round(base["open_fg3_pct"], 3)
                    if base["open_fg3_pct"] is not None else None
                ),
            },
            "windows": windows,
            "streaks": _streaks(games, base["fg3_pct"], column="FG3_PCT"),
        }

    def _mean(values):
        vals = [v for v in values if v is not None]
        return round(sum(vals) / len(vals), 3) if vals else 0

    spreads = [t["fg3_stdev"] for t in teams.values() if t["fg3_stdev"] is not None]
    return {
        "schema": SCHEMA,
        "league_average": round(sum(spreads) / len(spreads), 1) if spreads else 0,
        "league_fg3_pct": _mean(
            t["baseline"]["fg3_pct"] for t in teams.values()
        ),
        "windows": [label for label, _ in WINDOWS],
        "as_of": as_of.strftime("%Y-%m-%d"),
        "teams": teams,
    }


# Guard so importing this module never triggers nba_api calls.
# All nba_api access must go through the daily precompute (scripts/precompute.py).
if __name__ == "__main__":
    result = GetThreePointVariance("2024-25")

    print(f"Games through {result['as_of']}")
    print(f"League average game-to-game 3P% swing: {result['league_average']} pts\n")

    ranked = sorted(
        result["teams"].items(),
        key=lambda kv: kv[1]["baseline"]["fg3_pct"] or 0,
        reverse=True,
    )
    for name, row in ranked:
        base = row["baseline"]
        one = row["windows"].get("1 Week", {})
        print(
            f"{name:<24} {base['fg3_pct']:.1%} on {base['fg3a']:.1f} 3PA  "
            f"swing {row['fg3_stdev']:.1f}  1wk {one.get('swings')}"
        )

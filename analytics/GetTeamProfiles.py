"""Team profiles: where a team ranks, and what it actually runs.

Two halves, one fetch:

    offense   league ranks for the box score and efficiency stats, plus the
              play types the team runs and how well each one goes
    defense   ranks for what opponents manage against them, plus the play
              types opponents run at them

Ranks are computed here rather than taken from the API's own _RANK columns,
because those always rank highest-value-first. That is wrong for turnovers,
opponent points, and defensive rating, where the best team is the lowest. Each
stat below carries its own direction so rank 1 always means best.

Cost: three league-wide stat calls plus one per play type per side, each a
quick call, all in the cheap pass.
"""
import time
import pandas as pd

from nba_api.stats.endpoints import leaguedashteamstats, synergyplaytypes

# Bump whenever the stored shape changes, so precompute regenerates a finished
# season's file instead of leaving a stale one in place.
SCHEMA = 2

_TIMEOUT = 60

# (source frame, column, label, higher_is_better)
OFFENSE_STATS = (
    ("advanced", "OFF_RATING", "Offensive Rating", True),
    ("base", "PTS", "Points", True),
    ("base", "FG_PCT", "FG%", True),
    ("advanced", "EFG_PCT", "eFG%", True),
    ("advanced", "TS_PCT", "TS%", True),
    ("base", "FG3A", "3PA", True),
    ("base", "FG3_PCT", "3P%", True),
    ("base", "FT_PCT", "FT%", True),
    ("base", "AST", "Assists", True),
    ("base", "OREB", "Offensive Rebounds", True),
    ("base", "TOV", "Turnovers", False),
    ("advanced", "PACE", "Pace", True),
)

DEFENSE_STATS = (
    ("advanced", "DEF_RATING", "Defensive Rating", False),
    ("opponent", "OPP_PTS", "Opponent Points", False),
    ("opponent", "OPP_FG_PCT", "Opponent FG%", False),
    ("opponent", "OPP_FG3_PCT", "Opponent 3P%", False),
    ("opponent", "OPP_FG3A", "Opponent 3PA", False),
    ("opponent", "OPP_AST", "Opponent Assists", False),
    ("opponent", "OPP_TOV", "Turnovers Forced", True),
    ("base", "STL", "Steals", True),
    ("base", "BLK", "Blocks", True),
    ("base", "DREB", "Defensive Rebounds", True),
)

# Synergy's play type keys, with readable names.
PLAY_TYPES = (
    ("Transition", "Transition"),
    ("Isolation", "Isolation"),
    ("PRBallHandler", "Pick and Roll, Handler"),
    ("PRRollman", "Pick and Roll, Roll Man"),
    ("Postup", "Post Up"),
    ("Spotup", "Spot Up"),
    ("Handoff", "Hand Off"),
    ("Cut", "Cut"),
    ("OffScreen", "Off Screen"),
)

# Pause between the play type calls, which are numerous.
PAUSE = 0.8


def _retry(fetch, retries=3, pause=1.0):
    """Call `fetch`, retrying transient nba_api failures. Returns None if all fail."""
    for attempt in range(retries):
        try:
            return fetch()
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(pause * 2 ** attempt)
    return None


def _fetch_stats(season, season_type, measure_type):
    return _retry(
        lambda: leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            season_type_all_star=season_type,
            per_mode_detailed="PerGame",
            measure_type_detailed_defense=measure_type,
            timeout=_TIMEOUT,
        ).get_data_frames()[0]
    )


def _fetch_play_type(season, season_type, play_type, grouping):
    return _retry(
        lambda: synergyplaytypes.SynergyPlayTypes(
            league_id="00",
            season=season,
            season_type_all_star=season_type,
            per_mode_simple="PerGame",
            player_or_team_abbreviation="T",
            play_type_nullable=play_type,
            type_grouping_nullable=grouping,
            timeout=_TIMEOUT,
        ).get_data_frames()[0]
    )


def _ranked(frames, spec):
    """Value and league rank per team for each stat in `spec`.

    Returns {team_name: [{"stat", "value", "rank"}, ...]}, in spec order, and
    skips any stat whose source frame or column is missing.
    """
    out = {}
    for source, column, label, higher_is_better in spec:
        df = frames.get(source)
        if df is None or column not in df.columns or "TEAM_NAME" not in df.columns:
            continue

        values = pd.to_numeric(df[column], errors="coerce")
        # rank 1 is always the best, whichever direction that is for this stat.
        ranks = values.rank(ascending=not higher_is_better, method="min")

        # Rank 1 of 30 reads as the 100th percentile, rank 30 as the 0th.
        n = int(ranks.notna().sum())
        for team, value, rank in zip(df["TEAM_NAME"], values, ranks):
            if pd.isna(value) or pd.isna(rank):
                continue
            percentile = round((n - int(rank)) / (n - 1) * 100) if n > 1 else None
            out.setdefault(team, []).append({
                "stat": label,
                "value": round(float(value), 3),
                "rank": int(rank),
                "percentile": percentile,
            })
    return out


def _play_type_profile(season, season_type, grouping):
    """Frequency, efficiency and league percentile per play type, by team."""
    out = {}
    for key, label in PLAY_TYPES:
        df = _fetch_play_type(season, season_type, key, grouping)
        time.sleep(PAUSE)
        if df is None or df.empty or "TEAM_NAME" not in df.columns:
            continue
        if "POSS_PCT" not in df.columns:
            continue

        for _, row in df.iterrows():
            freq = pd.to_numeric(pd.Series([row.get("POSS_PCT")]), errors="coerce")[0]
            if pd.isna(freq):
                continue
            ppp = pd.to_numeric(pd.Series([row.get("PPP")]), errors="coerce")[0]
            pct = pd.to_numeric(pd.Series([row.get("PERCENTILE")]), errors="coerce")[0]
            out.setdefault(row["TEAM_NAME"], []).append({
                "type": label,
                "freq": round(float(freq), 3),
                "ppp": round(float(ppp), 3) if not pd.isna(ppp) else None,
                # Synergy reports percentile as a fraction; a whole number reads
                # better next to the rank column.
                "percentile": round(float(pct) * 100) if not pd.isna(pct) else None,
            })

    # Most run first, so the shape of a team's offense is the first thing read.
    for team, plays in out.items():
        plays.sort(key=lambda p: -p["freq"])
    return out


def GetTeamProfiles(SEASON, SEASON_TYPE="Regular Season"):
    """League ranks and play type mix for every team, both sides of the ball.

    Returns:
        {
            "schema": 1,
            "teams": {
                "Boston Celtics": {
                    "offense": {
                        "ranks": [{"stat": "Offensive Rating", "value": 119.5,
                                   "rank": 1, "percentile": 100}, ...],
                        "play_types": [{"type": "Spot Up", "freq": 0.24,
                                        "ppp": 1.09, "percentile": 82}, ...],
                    },
                    "defense": {"ranks": [...], "play_types": [...]},
                },
                ...
            },
        }

    Play types are what the team runs on offense, and what opponents run
    against them on defense. An empty `teams` dict means the stat calls failed;
    callers should treat that as "skip this stat", not as an error.
    """
    empty = {"schema": SCHEMA, "teams": {}}

    frames = {
        "base": _fetch_stats(SEASON, SEASON_TYPE, "Base"),
        "advanced": _fetch_stats(SEASON, SEASON_TYPE, "Advanced"),
        "opponent": _fetch_stats(SEASON, SEASON_TYPE, "Opponent"),
    }
    if all(f is None for f in frames.values()):
        return empty

    offense_ranks = _ranked(frames, OFFENSE_STATS)
    defense_ranks = _ranked(frames, DEFENSE_STATS)
    if not offense_ranks and not defense_ranks:
        return empty

    offense_plays = _play_type_profile(SEASON, SEASON_TYPE, "offensive")
    defense_plays = _play_type_profile(SEASON, SEASON_TYPE, "defensive")

    teams = {}
    for name in sorted(set(offense_ranks) | set(defense_ranks)):
        teams[name] = {
            "offense": {
                "ranks": offense_ranks.get(name, []),
                "play_types": offense_plays.get(name, []),
            },
            "defense": {
                "ranks": defense_ranks.get(name, []),
                "play_types": defense_plays.get(name, []),
            },
        }

    return {"schema": SCHEMA, "teams": teams}


# Guard so importing this module never triggers nba_api calls.
# All nba_api access must go through the daily precompute (scripts/precompute.py).
if __name__ == "__main__":
    result = GetTeamProfiles("2024-25")

    for name in ("Boston Celtics", "Orlando Magic"):
        t = result["teams"].get(name)
        if not t:
            continue
        print(f"\n=== {name} ===")
        for side in ("offense", "defense"):
            top = ", ".join(
                f"{r['stat']} #{r['rank']}" for r in t[side]["ranks"][:4]
            )
            plays = ", ".join(
                f"{p['type']} {p['freq']:.0%}" for p in t[side]["play_types"][:4]
            )
            print(f"  {side:<8} {top}")
            print(f"           {plays}")

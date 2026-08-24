
import time
import pandas as pd
from nba_api.stats.endpoints import leaguehustlestatsteam, leaguedashteamstats



_TIMEOUT = 60

_HUSTLE_COLUMNS = (
    "DEFLECTIONS",
    "CONTESTED_SHOTS",
    "LOOSE_BALLS_RECOVERED",
    "BOX_OUTS",
    "CHARGES_DRAWN",
    "SCREEN_ASSISTS",
)

# Offensive rebound rate is already a percentage, so it's compared directly
# rather than normalized by minutes.
_RATE_COLUMNS = ("OREB_PCT",)

# NBA hustle tracking begins in 2015-16; earlier seasons return nothing useful.
FIRST_HUSTLE_SEASON = "2015-16"


def _retry(fetch, retries=4, pause=1.0):
    """Call `fetch`, retrying transient nba_api failures. Returns None if all fail."""
    for attempt in range(retries):
        try:
            return fetch()
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(pause * 2 ** attempt)
    return None


def _team_frame(frames):
    """Pick the frame that actually holds per-team rows.

    Some hustle responses lead with a status/metadata frame, so index 0 isn't
    reliably the team table.
    """
    for df in frames:
        if df is not None and "TEAM_ID" in df.columns and not df.empty:
            return df
    return None


def _fetch_hustle(season, season_type, outcome):
    frames = _retry(
        lambda: leaguehustlestatsteam.LeagueHustleStatsTeam(
            season=season,
            season_type_all_star=season_type,
            per_mode_time="Totals",
            outcome_nullable=outcome,
            timeout=_TIMEOUT,
        ).get_data_frames()
    )
    return _team_frame(frames) if frames else None


def _fetch_advanced(season, season_type, outcome):
    frames = _retry(
        lambda: leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            season_type_all_star=season_type,
            per_mode_detailed="PerGame",
            measure_type_detailed_defense="Advanced",
            outcome_nullable=outcome,
            timeout=_TIMEOUT,
        ).get_data_frames()
    )
    return _team_frame(frames) if frames else None


def _per_minute(df, columns):
    """Normalize counting stats by team minutes played.

    Returns a frame indexed by TEAM_ID holding only the columns that were
    present and usable.
    """
    if df is None or "MIN" not in df.columns:
        return pd.DataFrame()

    out = pd.DataFrame(index=df["TEAM_ID"])
    minutes = pd.to_numeric(df["MIN"], errors="coerce").values
    for col in columns:
        if col in df.columns:
            values = pd.to_numeric(df[col], errors="coerce").values
            out[col] = values / minutes
    return out


def _rates(df, columns):
    """Pull already-normalized rate stats (e.g. OREB_PCT), indexed by TEAM_ID."""
    if df is None:
        return pd.DataFrame()

    out = pd.DataFrame(index=df["TEAM_ID"])
    for col in columns:
        if col in df.columns:
            out[col] = pd.to_numeric(df[col], errors="coerce").values
    return out


def GetEffortWhileLosing(SEASON, SEASON_TYPE="Regular Season"):
    """Effort-retention scores for all 30 teams in a season.

    For each effort component the team's rate in losses is divided by its rate
    in wins. A team at 1.0 competes the same either way; well under 1.0 means it
    packs the games in. The headline `effort_retention` is the mean of those
    component ratios.

    Returns:
        {
            "league_average": 0.96,       # mean effort_retention across teams
            "components": ["DEFLECTIONS", ...],   # components actually available
            "teams": {
                "Atlanta Hawks": {
                    "effort_retention": 0.91,
                    "z_score": -1.4,      # vs. the rest of the league
                    "components": {"DEFLECTIONS": 0.88, "OREB_PCT": 0.95, ...},
                },
                ...
            },
        }

    An empty `teams` dict means the source data wasn't available, most likely a
    pre-2015-16 season (no hustle tracking) or a season too young for every team
    to have both a win and a loss. Callers should treat that as "skip this
    stat", not as an error.
    """
    empty = {"league_average": 0, "components": [], "teams": {}}

    if SEASON < FIRST_HUSTLE_SEASON:
        return empty

    hustle_l = _fetch_hustle(SEASON, SEASON_TYPE, "L")
    time.sleep(1)
    hustle_w = _fetch_hustle(SEASON, SEASON_TYPE, "W")
    time.sleep(1)
    advanced_l = _fetch_advanced(SEASON, SEASON_TYPE, "L")
    time.sleep(1)
    advanced_w = _fetch_advanced(SEASON, SEASON_TYPE, "W")

    if hustle_l is None or hustle_w is None:
        return empty

    losing = pd.concat(
        [_per_minute(hustle_l, _HUSTLE_COLUMNS), _rates(advanced_l, _RATE_COLUMNS)],
        axis=1,
    )
    winning = pd.concat(
        [_per_minute(hustle_w, _HUSTLE_COLUMNS), _rates(advanced_w, _RATE_COLUMNS)],
        axis=1,
    )

    # Only components present on both sides can produce a ratio.
    components = [c for c in losing.columns if c in winning.columns]
    if not components:
        return empty

    losing, winning = losing[components], winning[components]

    # A zero denominator means the team has no wins yet (early season) or the
    # component wasn't recorded; NaN drops it from that team's mean instead of
    # producing an infinite ratio.
    ratios = losing / winning.where(winning != 0)
    ratios = ratios.replace([float("inf"), float("-inf")], pd.NA).astype(float)

    retention = ratios.mean(axis=1, skipna=True)
    retention = retention.dropna()
    if retention.empty:
        return empty

    std = retention.std()
    z_scores = (retention - retention.mean()) / std if std else retention * 0

    id_to_name = dict(zip(hustle_l["TEAM_ID"], hustle_l["TEAM_NAME"]))

    teams = {}
    for team_id, score in retention.items():
        name = id_to_name.get(team_id)
        if name is None:
            continue
        row = ratios.loc[team_id]
        teams[name] = {
            "effort_retention": round(float(score), 3),
            "z_score": round(float(z_scores.loc[team_id]), 2),
            "components": {
                c: round(float(row[c]), 3)
                for c in components
                if pd.notna(row[c])
            },
        }

    return {
        "league_average": round(float(retention.mean()), 3),
        "components": components,
        "teams": teams,
    }


# Guard so importing this module never triggers nba_api calls.
# All nba_api access must go through the daily precompute (scripts/precompute.py).
if __name__ == "__main__":
    result = GetEffortWhileLosing("2024-25")

    print(f"League average effort retention: {result['league_average']}")
    print(f"Components: {', '.join(result['components'])}\n")

    ranked = sorted(
        result["teams"].items(),
        key=lambda kv: kv[1]["effort_retention"],
        reverse=True,
    )
    for name, row in ranked:
        print(f"{row['effort_retention']:>6.3f}  (z {row['z_score']:+.2f})  {name}")

"""Per game player stats, grouped by team.

One league-wide call covers every player, which is then split by team so the
dashboard can show a roster next to the team tables without a call per team.

Traded players are a known wrinkle: the endpoint returns a single row per
player carrying their season totals, filed under the team they finished with.
So a midseason arrival shows their full season here, not just their time with
this team. TEAM_COUNT is kept so that case can be spotted.

Cheap: one call.
"""
import pandas as pd

from nba_api.stats.endpoints import leaguedashplayerstats
from nba_api.stats.static import teams as nba_teams

# Bump whenever the stored shape changes, so precompute regenerates a finished
# season's file instead of leaving a stale one in place.
SCHEMA = 1

_TIMEOUT = 60

# (source column, output key). Order sets the column order in the table.
COLUMNS = (
    ("PLAYER_NAME", "name"),
    ("GP", "gp"),
    ("MIN", "min"),
    ("PTS", "pts"),
    ("REB", "reb"),
    ("AST", "ast"),
    ("STL", "stl"),
    ("BLK", "blk"),
    ("TOV", "tov"),
    ("FG_PCT", "fg_pct"),
    ("FG3_PCT", "fg3_pct"),
    ("FT_PCT", "ft_pct"),
)


def _retry(fetch, retries=3, pause=1.0):
    """Call `fetch`, retrying transient nba_api failures. Returns None if all fail."""
    import time
    for attempt in range(retries):
        try:
            return fetch()
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(pause * 2 ** attempt)
    return None


def GetPlayerStats(SEASON, SEASON_TYPE="Regular Season"):
    """Per game stats for every player, keyed by full team name.

    Returns:
        {
            "schema": 1,
            "teams": {
                "Denver Nuggets": [
                    {"name": "Nikola Jokic", "gp": 70, "min": 36.7,
                     "pts": 29.6, "reb": 12.7, "ast": 10.2, "stl": 1.8,
                     "blk": 0.6, "tov": 3.2, "fg_pct": 0.576,
                     "fg3_pct": 0.417, "ft_pct": 0.8, "teams": 1},
                    ...
                ],
                ...
            },
        }

    Rosters are sorted by points per game. An empty `teams` dict means the call
    failed; callers should treat that as "skip this table", not as an error.
    """
    empty = {"schema": SCHEMA, "teams": {}}

    df = _retry(
        lambda: leaguedashplayerstats.LeagueDashPlayerStats(
            season=SEASON,
            season_type_all_star=SEASON_TYPE,
            per_mode_detailed="PerGame",
            timeout=_TIMEOUT,
        ).get_data_frames()[0]
    )
    if df is None or df.empty or "TEAM_ID" not in df.columns:
        return empty

    id_to_name = {t["id"]: t["full_name"] for t in nba_teams.get_teams()}

    teams = {}
    for _, row in df.iterrows():
        team = id_to_name.get(row["TEAM_ID"])
        if team is None:
            continue

        player = {}
        for source, key in COLUMNS:
            value = row.get(source)
            if key == "name":
                player[key] = value
                continue
            # Plain floats and ints: pandas hands back numpy scalars, which
            # precompute cannot JSON serialize.
            number = pd.to_numeric(pd.Series([value]), errors="coerce")[0]
            if pd.isna(number):
                player[key] = None
            elif key == "gp":
                player[key] = int(number)
            else:
                player[key] = round(float(number), 3)

        player["teams"] = int(row.get("TEAM_COUNT") or 1)
        teams.setdefault(team, []).append(player)

    for roster in teams.values():
        roster.sort(key=lambda p: -(p["pts"] or 0))

    return {"schema": SCHEMA, "teams": teams}


# Guard so importing this module never triggers nba_api calls.
# All nba_api access must go through the daily precompute (scripts/precompute.py).
if __name__ == "__main__":
    result = GetPlayerStats("2024-25")
    roster = result["teams"].get("Denver Nuggets", [])
    print(f"{len(result['teams'])} teams, {len(roster)} Nuggets\n")
    for p in roster[:6]:
        print(f"  {p['name']:<22} {p['gp']:>3}gp {p['min']:>5} min "
              f"{p['pts']:>5} pts {p['reb']:>5} reb {p['ast']:>5} ast")

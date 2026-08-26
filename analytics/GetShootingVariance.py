"""Shooting variance: what a team's shooting should look like, and what it has
actually looked like lately.

TThe baseline is what the season says to expect: efficiency (eFG%),
volume (attempts per game, three-point rate), and shot quality from tracking
data, meaning how much of a team's work comes from open and wide-open looks.
A team that generates open threes in volume is expected to shoot well, and a
cold stretch for that team means something different than the same stretch for
a team living on contested mid-range shots.

The last one, two, and three weeks of games measured
against that baseline, so the card can say whether a team is genuinely off or
merely inside its normal noise. `efg_stdev`, the game-to-game standard
deviation of eFG%, is what sets that bar: a swing of four points means little
for a high-variance team and a lot for a steady one.

Cheap: three league-wide calls, no per-game crawl.
"""
import time
import pandas as pd
from nba_api.stats.endpoints import teamgamelogs, leaguedashteamptshot


_TIMEOUT = 60

# Trailing windows, in days, measured back from the most recent game in the
# season's data rather than from today. That keeps the numbers stable for a
# finished season and correct if the refresh runs a day late.
WINDOWS = (("1 Week", 7), ("2 Weeks", 14), ("3 Weeks", 21))

# nba_api's closest-defender buckets that count as an uncontested look.
OPEN_RANGES = ("4-6 Feet - Open", "6+ Feet - Wide Open")

# Bump whenever the stored shape changes. Finished seasons are normally left
# alone once written, so precompute uses this to tell a stale file from a
# current one and regenerate it.
SCHEMA = 5


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


def _efg(fgm, fg3m, fga):
    """Effective field goal percentage, or None when there are no attempts.

    Returns a plain float; pandas sums arrive as numpy scalars, which precompute
    can't JSON serialize.
    """
    if not fga:
        return None
    return float((fgm + 0.5 * fg3m) / fga)


def _swings(gap, stdev):
    """Recent form on a 0 to 2 scale: 0 is cold, 1 is normal, 2 is hot.

    The window's gap is measured in the team's own standard deviations and then
    centered on 1, so a team shooting exactly its season average reads 1.00 and
    a full standard deviation either way reads 0 or 2. Beyond that the scale
    clamps: past one standard deviation the label stops changing, and the raw
    gap in points is reported alongside it anyway.
    """
    if not stdev:
        return None
    return round(max(0.0, min(2.0, 1 + gap / stdev)), 2)


def _streaks(games, baseline_rate, column="EFG"):
    """Hot and cold run lengths, plus how often a run continues.

    A game is hot when its rate beats the team's season mark and cold when it
    doesn't. `repeat_pct` is the share of games following a game on the current
    side that stayed on that side, which is the honest version of "is the next
    one likely hot": for most teams it lands near a coin flip, and saying so is
    more useful than implying the streak predicts anything.

    `column` picks the per-game rate, so the three-point stat can reuse this.
    """
    if baseline_rate is None or len(games) < 2:
        return None

    ordered = games.sort_values("GAME_DATE")
    sides = ["hot" if rate > baseline_rate else "cold" for rate in ordered[column]]

    # Run lengths, in order.
    runs = []
    for side in sides:
        if runs and runs[-1][0] == side:
            runs[-1][1] += 1
        else:
            runs.append([side, 1])

    direction = runs[-1][0]
    # How often a game on this side is followed by another on the same side.
    same, total = 0, 0
    for current, nxt in zip(sides, sides[1:]):
        if current == direction:
            total += 1
            same += int(nxt == direction)

    return {
        "avg_length": round(sum(r[1] for r in runs) / len(runs), 1),
        "longest": max(r[1] for r in runs),
        "current_direction": direction,
        "current_length": runs[-1][1],
        "repeat_pct": round(same / total, 3) if total else None,
    }


def _percentiles(values):
    """Map each value to its percentile rank within the population."""
    ordered = sorted(v for v in values if v is not None)
    out = {}
    for v in values:
        if v is None:
            out[v] = None
            continue
        below = sum(1 for o in ordered if o < v)
        out[v] = round(below / len(ordered) * 100)
    return out


def _fetch_game_logs(season, season_type):
    return _retry(
        lambda: teamgamelogs.TeamGameLogs(
            season_nullable=season,
            season_type_nullable=season_type,
            timeout=_TIMEOUT,
        ).get_data_frames()[0]
    )


def _fetch_open_shots(season, season_type):
    """Attempts and efficiency on open plus wide-open looks, keyed by TEAM_ID.

    Returns {} if the tracking calls fail, which simply drops the shot-quality
    half of the baseline instead of failing the whole stat.
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
        if df is None or "TEAM_ID" not in df.columns or "FGA" not in df.columns:
            return {}

        time.sleep(1)
        for _, row in df.iterrows():
            entry = totals.setdefault(row["TEAM_ID"], {"fga": 0.0, "fgm": 0.0, "fg3m": 0.0})
            entry["fga"] += float(row.get("FGA") or 0)
            entry["fgm"] += float(row.get("FGM") or 0)
            entry["fg3m"] += float(row.get("FG3M") or 0)
    return totals


def GetShootingVariance(SEASON, SEASON_TYPE="Regular Season"):
    """Shooting baseline plus recent-form windows for every team in a season.

    Returns:
        {
            "league_average": 4.2,   # mean efg_stdev across teams, in points
            "windows": ["1 Week", "2 Weeks", "3 Weeks"],
            "as_of": "2025-04-13",   # most recent game date in the data
            "teams": {
                "Atlanta Hawks": {
                    "efg_stdev": 4.6,          # game-to-game swing, in points
                    "baseline": {
                        "efg_pct": 0.548,
                        "efg_percentile": 72,
                        "fga": 88.4,           # per game
                        "fg3a": 37.1,          # per game
                        "fg3a_rate": 0.42,     # share of attempts from three
                        "open_share": 0.61,    # share of attempts uncontested
                        "open_share_percentile": 55,
                        "open_efg_pct": 0.581,
                    },
                    "windows": {
                        "1 Week": {"games": 3, "efg_pct": 0.512,
                                   "efg_delta_pts": -3.6, "fgm": 38.7,
                                   "fgm_delta": -2.8, "fga": 90.0,
                                   "fg3a": 39.3, "swings": 0.22},
                        ...
                    },
                    "streaks": {
                        "avg_length": 1.8,   # mean hot or cold run, in games
                        "longest": 6,
                        "current_direction": "hot",
                        "current_length": 3,
                        "repeat_pct": 0.51,  # a run continuing, historically
                    },
                },
                ...
            },
        }

    `swings` puts the window's eFG% gap on a 0 to 2 scale in standard
    deviations of that team's own game-to-game shooting: 0 is cold, 1 is
    normal, 2 is hot. A window with no games is omitted.

    An empty `teams` dict means the game logs couldn't be fetched. Callers
    should treat that as "skip this stat", not as an error.
    """
    empty = {"league_average": 0, "windows": [], "as_of": None, "teams": {}}

    logs = _fetch_game_logs(SEASON, SEASON_TYPE)
    if logs is None or logs.empty:
        return empty

    needed = ("TEAM_ID", "TEAM_NAME", "GAME_DATE", "FGM", "FGA", "FG3M", "FG3A")
    if any(c not in logs.columns for c in needed):
        return empty

    logs = logs[list(needed)].copy()
    logs["GAME_DATE"] = pd.to_datetime(logs["GAME_DATE"])
    for col in ("FGM", "FGA", "FG3M", "FG3A"):
        logs[col] = pd.to_numeric(logs[col], errors="coerce")
    logs = logs.dropna(subset=["FGA"])
    logs = logs[logs["FGA"] > 0]
    if logs.empty:
        return empty

    logs["EFG"] = (logs["FGM"] + 0.5 * logs["FG3M"]) / logs["FGA"]

    as_of = logs["GAME_DATE"].max()
    open_shots = _fetch_open_shots(SEASON, SEASON_TYPE)

    # Pass 1: per-team baselines, so league percentiles can be taken across them.
    baselines = {}
    for (team_id, team_name), games in logs.groupby(["TEAM_ID", "TEAM_NAME"]):
        played = len(games)
        fga, fgm = float(games["FGA"].sum()), float(games["FGM"].sum())
        fg3a, fg3m = float(games["FG3A"].sum()), float(games["FG3M"].sum())
        tracked = open_shots.get(team_id)

        baselines[team_name] = {
            "team_id": team_id,
            "games": games,
            "played": played,
            "efg_pct": _efg(fgm, fg3m, fga),
            # Sample stdev needs at least two games; a one-game season has no
            # meaningful spread to report.
            "efg_stdev": float(games["EFG"].std()) if played > 1 else None,
            # Makes per game and their spread, which is what the card shows:
            # a one-standard-deviation band of made shots reads more concretely
            # than a percentage of a percentage.
            "fgm": fgm / played,
            "fgm_stdev": float(games["FGM"].std()) if played > 1 else None,
            "fga": fga / played,
            "fg3a": fg3a / played,
            "fg3a_rate": (fg3a / fga) if fga else None,
            "open_share": (tracked["fga"] / fga) if tracked and fga else None,
            "open_efg_pct": (
                _efg(tracked["fgm"], tracked["fg3m"], tracked["fga"])
                if tracked else None
            ),
        }

    efg_ranks = _percentiles([b["efg_pct"] for b in baselines.values()])
    open_ranks = _percentiles([b["open_share"] for b in baselines.values()])

    # Pass 2: recent-form windows against each team's own baseline.
    teams = {}
    for team_name, base in baselines.items():
        games = base["games"]
        stdev = base["efg_stdev"]

        windows = {}
        for label, days in WINDOWS:
            recent = games[games["GAME_DATE"] > as_of - pd.Timedelta(days=days)]
            if recent.empty:
                continue

            played = len(recent)
            w_fga, w_fgm = float(recent["FGA"].sum()), float(recent["FGM"].sum())
            w_fg3a, w_fg3m = float(recent["FG3A"].sum()), float(recent["FG3M"].sum())
            w_efg = _efg(w_fgm, w_fg3m, w_fga)
            if w_efg is None or base["efg_pct"] is None:
                continue

            gap = w_efg - base["efg_pct"]
            windows[label] = {
                "games": played,
                "efg_pct": round(w_efg, 3),
                "efg_delta_pts": round(gap * 100, 1),
                "fgm": round(w_fgm / played, 1),
                # Normalized against the team's own season average, so the
                # column reads as makes gained or lost per game rather than a
                # raw count that means nothing without the baseline alongside.
                "fgm_delta": round(w_fgm / played - base["fgm"], 1),
                "fga": round(w_fga / played, 1),
                "fg3a": round(w_fg3a / played, 1),
                "swings": _swings(gap, stdev),
            }

        teams[team_name] = {
            "efg_stdev": round(stdev * 100, 1) if stdev is not None else None,
            "baseline": {
                "efg_pct": round(base["efg_pct"], 3) if base["efg_pct"] is not None else None,
                "efg_percentile": efg_ranks.get(base["efg_pct"]),
                "fgm": round(base["fgm"], 1),
                "fgm_stdev": (
                    round(base["fgm_stdev"], 1)
                    if base["fgm_stdev"] is not None else None
                ),
                "fga": round(base["fga"], 1),
                "fg3a": round(base["fg3a"], 1),
                "fg3a_rate": round(base["fg3a_rate"], 3) if base["fg3a_rate"] is not None else None,
                "open_share": round(base["open_share"], 3) if base["open_share"] is not None else None,
                "open_share_percentile": open_ranks.get(base["open_share"]),
                "open_efg_pct": (
                    round(base["open_efg_pct"], 3)
                    if base["open_efg_pct"] is not None else None
                ),
            },
            "windows": windows,
            "streaks": _streaks(games, base["efg_pct"]),
        }

    def _mean(values):
        vals = [v for v in values if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else 0

    # League reference points: the average team's eFG% swing (what decides
    # steady vs. streaky) and the average team's makes per game and spread
    # (what the card's comparison band is drawn from).
    return {
        "schema": SCHEMA,
        "league_average": _mean(t["efg_stdev"] for t in teams.values()),
        "league_fgm": _mean(t["baseline"]["fgm"] for t in teams.values()),
        "league_fgm_stdev": _mean(t["baseline"]["fgm_stdev"] for t in teams.values()),
        "windows": [label for label, _ in WINDOWS],
        "as_of": as_of.strftime("%Y-%m-%d"),
        "teams": teams,
    }


# Guard so importing this module never triggers nba_api calls.
# All nba_api access must go through the daily precompute (scripts/precompute.py).
if __name__ == "__main__":
    result = GetShootingVariance("2024-25")

    print(f"Games through {result['as_of']}")
    print(f"League average game-to-game eFG% swing: {result['league_average']} pts\n")

    ranked = sorted(
        result["teams"].items(),
        key=lambda kv: kv[1]["windows"].get("2 Weeks", {}).get("efg_delta_pts", 0),
    )
    for name, row in ranked:
        base = row["baseline"]
        two = row["windows"].get("2 Weeks", {})
        print(
            f"{name:<24} season {base['efg_pct']:.3f} "
            f"(p{base['efg_percentile']})  "
            f"2wk {two.get('efg_delta_pts', 0):+.1f} pts "
            f"({two.get('swings')} sd)"
        )

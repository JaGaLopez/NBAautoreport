"""Hot starts: how often a team is ahead after one quarter and at halftime.

The interesting part isn't either rate on its own, it's whether a first-quarter
lead actually holds. Every team leads at half more often when it led after one
quarter, since the first quarter is part of the half, so the raw pairing is
correlated by construction. What separates teams is the *lift*: how much better
than their own baseline halftime-lead rate they do when the start goes well.
A big lift means starts carry the game; a small one means the start gets given
back.

Cost note: this crawls one line score per game, the same data GetQ4Comebacks
walks. If the daily refresh gets tight, merging the two into a single pass over
the season's line scores is the obvious optimization.
"""
import time
import pandas as pd
from nba_api.stats.static import teams as nba_teams

# Reuses the retry/backoff fetchers from the comebacks module rather than
# duplicating them; both modules need exactly the same throttled calls.
from analytics.GetQ4Comebacks import _fetch_line_score, _fetch_game_log


def _quarter(row, *keys):
    """Sum the given quarter columns, or None if any is missing.

    BoxScoreSummaryV2 has a known data-availability gap where a LineScore row
    exists but its PTS_QTR* values come back as None/NaN. Those games can't be
    classified and are skipped by the caller.
    """
    total = 0
    for key in keys:
        value = row[key]
        if value is None or pd.isna(value):
            return None
        total += value
    return total


def GetAllTeamsHotStarts(SEASON):
    """First-quarter and halftime lead rates for every team in a season.

    Ties are not leads: a team tied after one quarter is counted as not
    leading, in both the numerator and the conditional.

    Returns:
        {
            "league_average": 0.5,       # mean q1_lead_pct across all 30 teams
            "teams": {
                "Atlanta Hawks": {
                    "games": 82,
                    "q1_leads": 45,
                    "q1_lead_pct": 0.549,
                    "h1_leads": 43,
                    "h1_lead_pct": 0.524,
                    "h1_lead_after_q1_lead": 36,
                    "h1_lead_after_q1_lead_pct": 0.8,
                    "lift_pts": 27.6,    # conditional minus baseline, in points
                },
                ...
            },
        }

    An empty `teams` dict means no game data could be fetched. Callers should
    treat that as "skip this stat", not as an error.
    """
    all_teams = nba_teams.get_teams()
    id_to_name = {t["id"]: t["full_name"] for t in all_teams}

    # Gather every unique game id in the season from each team's game log.
    game_ids = set()
    for t in all_teams:
        gl = _fetch_game_log(t["id"], SEASON)
        if gl is None:
            continue
        game_ids.update(gl["Game_ID"].tolist())
        time.sleep(0.6)

    tally = {
        t["id"]: {"games": 0, "q1": 0, "h1": 0, "both": 0}
        for t in all_teams
    }

    for game_id in sorted(game_ids):
        time.sleep(0.6)

        line_score = _fetch_line_score(game_id)
        # Skip games whose box score can't be fetched rather than aborting the
        # whole season; a partial but real result beats no file at all.
        if line_score is None or len(line_score) < 2:
            continue

        a, b = line_score.iloc[0], line_score.iloc[1]
        a_q1, b_q1 = _quarter(a, "PTS_QTR1"), _quarter(b, "PTS_QTR1")
        a_h1 = _quarter(a, "PTS_QTR1", "PTS_QTR2")
        b_h1 = _quarter(b, "PTS_QTR1", "PTS_QTR2")
        if None in (a_q1, b_q1, a_h1, b_h1):
            continue

        for team, q1, opp_q1, h1, opp_h1 in (
            (a, a_q1, b_q1, a_h1, b_h1),
            (b, b_q1, a_q1, b_h1, a_h1),
        ):
            row = tally.get(team["TEAM_ID"])
            if row is None:
                continue
            # bool()/int() rather than the numpy scalars pandas hands back,
            # so the tallies stay JSON serializable for precompute.
            row["games"] += 1
            led_q1 = bool(q1 > opp_q1)
            led_h1 = bool(h1 > opp_h1)
            row["q1"] += int(led_q1)
            row["h1"] += int(led_h1)
            row["both"] += int(led_q1 and led_h1)

    teams = {}
    for team_id, row in tally.items():
        name = id_to_name.get(team_id)
        if name is None or row["games"] == 0:
            continue

        q1_pct = row["q1"] / row["games"]
        h1_pct = row["h1"] / row["games"]
        # Conditional is undefined for a team that never led after one quarter.
        conditional = row["both"] / row["q1"] if row["q1"] else None

        teams[name] = {
            "games": row["games"],
            "q1_leads": row["q1"],
            "q1_lead_pct": round(q1_pct, 3),
            "h1_leads": row["h1"],
            "h1_lead_pct": round(h1_pct, 3),
            "h1_lead_after_q1_lead": row["both"],
            "h1_lead_after_q1_lead_pct": (
                round(conditional, 3) if conditional is not None else None
            ),
            "lift_pts": (
                round((conditional - h1_pct) * 100, 1)
                if conditional is not None else None
            ),
        }

    if not teams:
        return {"league_average": 0, "teams": {}}

    league_average = sum(t["q1_lead_pct"] for t in teams.values()) / len(teams)
    return {"league_average": round(league_average, 3), "teams": teams}


# Guard so importing this module never triggers nba_api calls.
# All nba_api access must go through the daily precompute (scripts/precompute.py).
if __name__ == "__main__":
    result = GetAllTeamsHotStarts("2024-25")

    print(f"League average Q1 lead rate: {result['league_average']:.1%}\n")
    ranked = sorted(
        result["teams"].items(),
        key=lambda kv: kv[1]["q1_lead_pct"],
        reverse=True,
    )
    for name, row in ranked:
        lift = row["lift_pts"]
        lift_text = f"{lift:+.1f} pts" if lift is not None else "n/a"
        print(
            f"{row['q1_lead_pct']:>6.1%} Q1  {row['h1_lead_pct']:>6.1%} H1  "
            f"lift {lift_text:>10}  {name}"
        )

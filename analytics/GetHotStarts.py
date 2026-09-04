"""Hot starts: how often a team is ahead after one quarter and at halftime.

The interesting part isn't either rate on its own, it's whether a first-quarter
lead actually holds. Every team leads at half more often when it led after one
quarter, since the first quarter is part of the half, so the raw pairing is
correlated by construction. What separates teams is the *lift*: how much better
than their own baseline halftime-lead rate they do when the start goes well.


Cost note: this crawls one line score per game, the same data GetQ4Comebacks
walks. If the daily refresh gets tight, merging the two into a single pass over
the season's line scores is the obvious optimization.
"""
import pandas as pd
from nba_api.stats.static import teams as nba_teams

# A lead only counts as a start once it is this many points. A one-point edge
# after twelve minutes is noise, not a hot start.
MIN_LEAD = 5

# Bump whenever the stored shape changes, so precompute regenerates a finished
# season's file instead of leaving a stale one in place.
SCHEMA = 3

# The line score crawl is shared with the other stats built on it, so one pass
# over the season can feed all of them. See analytics/LineScores.py.
from analytics.LineScores import iter_line_scores


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


def new_tally():
    """Empty accumulator: every team present with zero games."""
    return {
        t["id"]: {"games": 0, "wins": 0, "q1": 0, "h1": 0, "held": 0,
                  "q1_wins": 0, "held_wins": 0}
        for t in nba_teams.get_teams()
    }


def add_game(tally, game_id, line_score):
    """Fold one game's line score into the tally.

    Games with incomplete quarter data are ignored; they can't be classified
    either way.
    """
    a, b = line_score.iloc[0], line_score.iloc[1]
    a_q1, b_q1 = _quarter(a, "PTS_QTR1"), _quarter(b, "PTS_QTR1")
    a_h1 = _quarter(a, "PTS_QTR1", "PTS_QTR2")
    b_h1 = _quarter(b, "PTS_QTR1", "PTS_QTR2")
    if None in (a_q1, b_q1, a_h1, b_h1):
        return

    # The final score decides the win, so a start can be measured against
    # whether it was actually converted.
    a_pts, b_pts = a.get("PTS"), b.get("PTS")
    if a_pts is None or b_pts is None or pd.isna(a_pts) or pd.isna(b_pts):
        return

    for team, q1, opp_q1, h1, opp_h1, pts, opp_pts in (
        (a, a_q1, b_q1, a_h1, b_h1, a_pts, b_pts),
        (b, b_q1, a_q1, b_h1, a_h1, b_pts, a_pts),
    ):
        row = tally.get(team["TEAM_ID"])
        if row is None:
            continue

        q1_margin = q1 - opp_q1
        h1_margin = h1 - opp_h1

        # bool()/int() rather than the numpy scalars pandas hands back,
        # so the tallies stay JSON serializable for precompute.
        won = bool(pts > opp_pts)
        row["games"] += 1
        row["wins"] += int(won)

        led_q1 = bool(q1_margin >= MIN_LEAD)
        led_h1 = bool(h1_margin >= MIN_LEAD)
        row["q1"] += int(led_q1)
        row["h1"] += int(led_h1)
        row["q1_wins"] += int(led_q1 and won)

        # Held means the halftime lead is at least as big as the one after the
        # first quarter, so a start that gets whittled away doesn't count.
        held = led_q1 and bool(h1_margin >= q1_margin)
        row["held"] += int(held)
        row["held_wins"] += int(held and won)


def finish(tally):
    """Turn a tally into the stored {league_average, teams} payload."""
    id_to_name = {t["id"]: t["full_name"] for t in nba_teams.get_teams()}

    teams = {}
    for team_id, row in tally.items():
        name = id_to_name.get(team_id)
        if name is None or row["games"] == 0:
            continue

        q1_pct = row["q1"] / row["games"]
        h1_pct = row["h1"] / row["games"]
        # Undefined for a team that never opened a qualifying lead at all.
        held_pct = row["held"] / row["q1"] if row["q1"] else None

        # Win rate in each scenario, and how far above the team's own baseline
        # that is. The lift is the point: every team wins more when it leads,
        # so the raw rate says little on its own.
        win_pct = row["wins"] / row["games"]
        q1_win_pct = row["q1_wins"] / row["q1"] if row["q1"] else None
        held_win_pct = row["held_wins"] / row["held"] if row["held"] else None

        teams[name] = {
            "games": row["games"],
            "wins": row["wins"],
            "win_pct": round(win_pct, 3),
            "q1_leads": row["q1"],
            "q1_lead_pct": round(q1_pct, 3),
            "q1_wins": row["q1_wins"],
            "q1_win_pct": round(q1_win_pct, 3) if q1_win_pct is not None else None,
            "q1_win_lift": (
                round((q1_win_pct - win_pct) * 100, 1)
                if q1_win_pct is not None else None
            ),
            "h1_leads": row["h1"],
            "h1_lead_pct": round(h1_pct, 3),
            "held": row["held"],
            "held_pct": round(held_pct, 3) if held_pct is not None else None,
            "held_wins": row["held_wins"],
            "held_win_pct": (
                round(held_win_pct, 3) if held_win_pct is not None else None
            ),
            "held_win_lift": (
                round((held_win_pct - win_pct) * 100, 1)
                if held_win_pct is not None else None
            ),
        }

    if not teams:
        return {"schema": SCHEMA, "league_average": 0, "teams": {}}

    def _mean(key):
        vals = [t[key] for t in teams.values() if t.get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    # League average lift, so a team can be told apart from the league-wide
    # effect of simply being ahead.
    league_q1_lift = _mean("q1_win_lift")
    league_held_lift = _mean("held_win_lift")

    for t in teams.values():
        for key, league in (("q1_win_lift", league_q1_lift),
                            ("held_win_lift", league_held_lift)):
            value = t.get(key)
            t[key + "_vs_league"] = (
                round(value - league, 1)
                if value is not None and league is not None else None
            )

    league_average = sum(t["q1_lead_pct"] for t in teams.values()) / len(teams)
    return {
        "schema": SCHEMA,
        "league_average": round(league_average, 3),
        "league_q1_win_lift": league_q1_lift,
        "league_held_win_lift": league_held_lift,
        "teams": teams,
    }


def GetAllTeamsHotStarts(SEASON):
    """First-quarter and halftime lead rates for every team in a season.

    A lead counts only at MIN_LEAD points or more, so narrow edges that mean
    nothing after twelve minutes are excluded. "Held" is the stricter test: the
    team opened a qualifying first-quarter lead and carried at least that much
    of it into halftime.

    This runs the line score crawl for this stat alone. The daily precompute
    instead drives new_tally/add_game/finish directly so one crawl feeds every
    stat built on line scores.

    Returns:
        {
            "league_average": 0.3,       # mean q1_lead_pct across all 30 teams
            "teams": {
                "Atlanta Hawks": {
                    "games": 82,
                    "q1_leads": 27,      # led by MIN_LEAD+ after one quarter
                    "q1_lead_pct": 0.329,
                    "h1_leads": 30,      # led by MIN_LEAD+ at halftime
                    "h1_lead_pct": 0.366,
                    "held": 15,          # of the 27, kept a lead that big
                    "held_pct": 0.556,
                },
                ...
            },
        }

    An empty `teams` dict means no game data could be fetched. Callers should
    treat that as "skip this stat", not as an error.
    """
    tally = new_tally()
    for game_id, line_score in iter_line_scores(SEASON):
        add_game(tally, game_id, line_score)
    return finish(tally)


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
        held = row["held_pct"]
        held_text = f"{held:.1%}" if held is not None else "n/a"
        print(
            f"{row['q1_lead_pct']:>6.1%} Q1  {row['h1_lead_pct']:>6.1%} H1  "
            f"held {held_text:>7}  {name}"
        )

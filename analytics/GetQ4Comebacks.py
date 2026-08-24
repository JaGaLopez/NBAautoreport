import time
import pandas as pd
from nba_api.stats.endpoints import teamgamelog
from nba_api.stats.static import teams as nba_teams

# The line score crawl is shared with the other stats built on it, so one pass
# over the season can feed all of them. See analytics/LineScores.py.
from analytics.LineScores import PAUSE, fetch_line_score, iter_line_scores


def _pts_after_q3(row):
    """Sum of a team's first three quarters, or None if any are missing.

    BoxScoreSummaryV2 has a known data-availability gap (notably games on or
    after 4/10/2025): the LineScore row is present but its PTS_QTR* values come
    back as None/NaN. Those games can't be classified as comebacks, so callers
    skip them instead of crashing on `None + None`.
    """
    qtrs = (row["PTS_QTR1"], row["PTS_QTR2"], row["PTS_QTR3"])
    if any(q is None or pd.isna(q) for q in qtrs):
        return None
    return qtrs[0] + qtrs[1] + qtrs[2]


def _resolve_team_id(team_identifier):
    all_teams = nba_teams.get_teams()
    if isinstance(team_identifier, int):
        return team_identifier
    match = next(
        (t for t in all_teams if t["abbreviation"].upper() == team_identifier.upper()),
        None,
    )
    if match is None:
        raise ValueError(f"Team not found: {team_identifier}")
    return match["id"]


def GetQ4Comebacks(team_identifier, SEASON):
    """
    Returns a DataFrame of 4th quarter comebacks for a team in a given season.
    A comeback is trailing after 3 quarters but winning the final game.

    Args:
        team_identifier: team abbreviation (e.g. "LAL") or integer team ID
        SEASON: season string (e.g. "2023-24")
    """
    team_id = _resolve_team_id(team_identifier)

    games_df = teamgamelog.TeamGameLog(
        team_id=team_id,
        season=SEASON,
        season_type_all_star="Regular Season",
    ).get_data_frames()[0]

    comebacks = []

    for _, game in games_df.iterrows():
        game_id = game["Game_ID"]
        time.sleep(PAUSE)

        line_score = fetch_line_score(game_id)
        if line_score is None:
            continue

        team_row = line_score[line_score["TEAM_ID"] == team_id]
        opp_row = line_score[line_score["TEAM_ID"] != team_id]

        if team_row.empty or opp_row.empty:
            continue

        team = team_row.iloc[0]
        opp = opp_row.iloc[0]

        team_after_q3 = _pts_after_q3(team)
        opp_after_q3 = _pts_after_q3(opp)
        if team_after_q3 is None or opp_after_q3 is None:
            continue

        if team_after_q3 < opp_after_q3 and team["PTS"] > opp["PTS"]:
            comebacks.append(
                {
                    "GAME_ID": game_id,
                    "GAME_DATE": game["GAME_DATE"],
                    "MATCHUP": game["MATCHUP"],
                    "TEAM_SCORE_AFTER_Q3": int(team_after_q3),
                    "OPP_SCORE_AFTER_Q3": int(opp_after_q3),
                    "DEFICIT_AFTER_Q3": int(opp_after_q3 - team_after_q3),
                    "FINAL_TEAM": int(team["PTS"]),
                    "FINAL_OPP": int(opp["PTS"]),
                }
            )

    comeback_df = pd.DataFrame(comebacks)
    return comeback_df


def GetQ4ComebackCount(team_identifier, SEASON):
    """Returns just the count of 4th quarter comebacks."""
    return len(GetQ4Comebacks(team_identifier, SEASON))


def new_tally():
    """Empty accumulator: every team present with zero comebacks."""
    return {t["full_name"]: {"count": 0, "games": []} for t in nba_teams.get_teams()}


def add_game(tally, game_id, line_score):
    """Fold one game's line score into the tally.

    Games with incomplete quarter data are ignored rather than crashing on the
    arithmetic; they can't be classified either way.
    """
    id_to_name = {t["id"]: t["full_name"] for t in nba_teams.get_teams()}

    a, b = line_score.iloc[0], line_score.iloc[1]
    a_q3, b_q3 = _pts_after_q3(a), _pts_after_q3(b)
    if a_q3 is None or b_q3 is None:
        return

    for team, opp, team_after_q3, opp_after_q3 in (
        (a, b, a_q3, b_q3),
        (b, a, b_q3, a_q3),
    ):
        if team_after_q3 < opp_after_q3 and team["PTS"] > opp["PTS"]:
            name = id_to_name.get(team["TEAM_ID"])
            if name is None:
                continue
            tally[name]["count"] += 1
            tally[name]["games"].append(
                {
                    "GAME_ID": game_id,
                    "GAME_DATE": str(team["GAME_DATE_EST"]),
                    "MATCHUP": f'{team["TEAM_ABBREVIATION"]} vs. {opp["TEAM_ABBREVIATION"]}',
                    "DEFICIT_AFTER_Q3": int(opp_after_q3 - team_after_q3),
                    "FINAL_TEAM": int(team["PTS"]),
                    "FINAL_OPP": int(opp["PTS"]),
                }
            )


def finish(tally):
    """Turn a tally into the stored {league_average, teams} payload."""
    counts = [r["count"] for r in tally.values()]
    league_average = round(sum(counts) / len(counts), 2) if counts else 0
    return {"league_average": league_average, "teams": tally}


def GetAllTeamsQ4Comebacks(SEASON):
    """
    4th-quarter comeback counts for every team in a season, computed in a single
    pass. Each game's box score is fetched only once (the LineScore frame holds
    both teams), so this is roughly half the API calls of looping GetQ4Comebacks
    over all 30 teams. Same comeback rule: trailing after three quarters but
    winning the game.

    This runs the line score crawl for this stat alone. The daily precompute
    instead drives new_tally/add_game/finish directly so one crawl feeds every
    stat built on line scores.

    Returns:
        {
            "league_average": 2.4,   # mean comeback count across all 30 teams
            "teams": {
                "Atlanta Hawks": {
                    "count": 3,
                    "games": [
                        {"GAME_ID": "...", "GAME_DATE": "...", "MATCHUP": "ATL vs. BOS",
                         "DEFICIT_AFTER_Q3": 8, "FINAL_TEAM": 110, "FINAL_OPP": 105},
                        ...
                    ],
                },
                ...
            },
        }

    The league average lets the UI rank "narrative" stats by how far a team
    sits from the rest of the league.
    """
    tally = new_tally()
    for game_id, line_score in iter_line_scores(SEASON):
        add_game(tally, game_id, line_score)
    return finish(tally)

import time
import pandas as pd
from nba_api.stats.endpoints import teamgamelog, boxscoresummaryv2
from nba_api.stats.static import teams as nba_teams


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
        time.sleep(0.6)

        line_score = boxscoresummaryv2.BoxScoreSummaryV2(
            game_id=game_id
        ).get_data_frames()[5]

        team_row = line_score[line_score["TEAM_ID"] == team_id]
        opp_row = line_score[line_score["TEAM_ID"] != team_id]

        if team_row.empty or opp_row.empty:
            continue

        team = team_row.iloc[0]
        opp = opp_row.iloc[0]

        team_after_q3 = team["PTS_QTR1"] + team["PTS_QTR2"] + team["PTS_QTR3"]
        opp_after_q3 = opp["PTS_QTR1"] + opp["PTS_QTR2"] + opp["PTS_QTR3"]

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

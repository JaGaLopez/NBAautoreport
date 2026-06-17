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


def GetAllTeamsQ4Comebacks(SEASON):
    """
    4th-quarter comeback counts for every team in a season, computed in a single
    pass. Each game's box score is fetched only once (the LineScore frame holds
    both teams), so this is roughly half the API calls of looping GetQ4Comebacks
    over all 30 teams. Same comeback rule: trailing after three quarters but
    winning the game.

    Returns a dict keyed by team full name (matching TEAM_NAME used elsewhere):
        {
            "Atlanta Hawks": {
                "count": 3,
                "games": [
                    {"GAME_ID": "...", "GAME_DATE": "...", "MATCHUP": "ATL vs. BOS",
                     "DEFICIT_AFTER_Q3": 8, "FINAL_TEAM": 110, "FINAL_OPP": 105},
                    ...
                ],
            },
            ...
        }
    """
    all_teams = nba_teams.get_teams()
    id_to_name = {t["id"]: t["full_name"] for t in all_teams}

    # Gather every unique game id in the season from each team's game log.
    game_ids = set()
    for t in all_teams:
        gl = teamgamelog.TeamGameLog(
            team_id=t["id"],
            season=SEASON,
            season_type_all_star="Regular Season",
        ).get_data_frames()[0]
        game_ids.update(gl["Game_ID"].tolist())
        time.sleep(0.6)

    results = {t["full_name"]: {"count": 0, "games": []} for t in all_teams}

    for game_id in sorted(game_ids):
        time.sleep(0.6)

        line_score = boxscoresummaryv2.BoxScoreSummaryV2(
            game_id=game_id
        ).get_data_frames()[5]

        if len(line_score) < 2:
            continue

        a, b = line_score.iloc[0], line_score.iloc[1]
        for team, opp in ((a, b), (b, a)):
            team_after_q3 = team["PTS_QTR1"] + team["PTS_QTR2"] + team["PTS_QTR3"]
            opp_after_q3 = opp["PTS_QTR1"] + opp["PTS_QTR2"] + opp["PTS_QTR3"]

            if team_after_q3 < opp_after_q3 and team["PTS"] > opp["PTS"]:
                name = id_to_name.get(team["TEAM_ID"])
                if name is None:
                    continue
                results[name]["count"] += 1
                results[name]["games"].append(
                    {
                        "GAME_ID": game_id,
                        "GAME_DATE": str(team["GAME_DATE_EST"]),
                        "MATCHUP": f'{team["TEAM_ABBREVIATION"]} vs. {opp["TEAM_ABBREVIATION"]}',
                        "DEFICIT_AFTER_Q3": int(opp_after_q3 - team_after_q3),
                        "FINAL_TEAM": int(team["PTS"]),
                        "FINAL_OPP": int(opp["PTS"]),
                    }
                )

    return results

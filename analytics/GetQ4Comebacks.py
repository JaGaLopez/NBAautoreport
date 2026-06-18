import time
import pandas as pd
from nba_api.stats.endpoints import teamgamelog, boxscoresummaryv2
from nba_api.stats.static import teams as nba_teams


# nba_api defaults to a 30s read timeout; stats.nba.com throttles datacenter
# IPs, so give each call more room and retry with exponential backoff.
_TIMEOUT = 60


def _fetch_line_score(game_id, retries=4, pause=1.0):
    """Fetch a game's LineScore frame, retrying transient nba_api failures.

    Returns the DataFrame, or None if it can't be fetched. A single dropped
    call (rate limit / timeout) is common when running from a server IP, and
    must not abort an entire season's worth of box scores.
    """
    for attempt in range(retries):
        try:
            return boxscoresummaryv2.BoxScoreSummaryV2(
                game_id=game_id, timeout=_TIMEOUT
            ).get_data_frames()[5]
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(pause * 2 ** attempt)
    return None


def _fetch_game_log(team_id, season, retries=4, pause=1.0):
    """Fetch a team's regular-season game log, retrying transient failures.

    Returns the DataFrame, or None if it can't be fetched. Skipping a failed
    log loses almost nothing: every game appears in *both* teams' logs, so the
    other 29 logs still surface nearly all game ids.
    """
    for attempt in range(retries):
        try:
            return teamgamelog.TeamGameLog(
                team_id=team_id,
                season=season,
                season_type_all_star="Regular Season",
                timeout=_TIMEOUT,
            ).get_data_frames()[0]
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(pause * 2 ** attempt)
    return None


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
        gl = _fetch_game_log(t["id"], SEASON)
        if gl is None:
            continue
        game_ids.update(gl["Game_ID"].tolist())
        time.sleep(0.6)

    results = {t["full_name"]: {"count": 0, "games": []} for t in all_teams}

    for game_id in sorted(game_ids):
        time.sleep(0.6)

        line_score = _fetch_line_score(game_id)
        # Skip games whose box score can't be fetched rather than aborting the
        # whole season — a partial-but-real result is far better than no file.
        if line_score is None or len(line_score) < 2:
            continue

        a, b = line_score.iloc[0], line_score.iloc[1]
        a_q3, b_q3 = _pts_after_q3(a), _pts_after_q3(b)
        # Skip games with incomplete quarter data rather than crashing on the
        # arithmetic; they can't be classified either way.
        if a_q3 is None or b_q3 is None:
            continue

        for team, opp, team_after_q3, opp_after_q3 in (
            (a, b, a_q3, b_q3),
            (b, a, b_q3, a_q3),
        ):
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

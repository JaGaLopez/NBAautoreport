"""Shared access to a season's box score line scores.

Several narrative stats need the same thing: every game's quarter-by-quarter
line score. Fetching that is by far the most expensive work the daily refresh
does, roughly 1,200 throttled calls per season, so it lives here once and the
stats that need it consume the same pass rather than each crawling the season
themselves.

Stat modules built on this expose three pieces so a caller can drive them
without repeating the fetch:

    new_tally()                     empty accumulator
    add_game(tally, game_id, ls)    fold one game in
    finish(tally)                   the finished {league_average, teams} dict

Their Get* functions stay usable on their own; they just run this crawl for a
single stat.
"""
import time
from nba_api.stats.endpoints import teamgamelog, boxscoresummaryv2
from nba_api.stats.static import teams as nba_teams


# nba_api defaults to a 30s read timeout; stats.nba.com throttles datacenter
# IPs, so give each call more room and retry with exponential backoff.
TIMEOUT = 60

# Pause between calls, to stay under the throttle when running from a server IP.
PAUSE = 0.6


def fetch_line_score(game_id, retries=4, pause=1.0):
    """Fetch a game's LineScore frame, retrying transient nba_api failures.

    Returns the DataFrame, or None if it can't be fetched. A single dropped
    call (rate limit / timeout) is common when running from a server IP, and
    must not abort an entire season's worth of box scores.
    """
    for attempt in range(retries):
        try:
            return boxscoresummaryv2.BoxScoreSummaryV2(
                game_id=game_id, timeout=TIMEOUT
            ).get_data_frames()[5]
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(pause * 2 ** attempt)
    return None


def fetch_game_log(team_id, season, retries=4, pause=1.0):
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
                timeout=TIMEOUT,
            ).get_data_frames()[0]
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(pause * 2 ** attempt)
    return None


def season_game_ids(season):
    """Every unique regular-season game id, gathered from all 30 team logs."""
    game_ids = set()
    for t in nba_teams.get_teams():
        gl = fetch_game_log(t["id"], season)
        if gl is None:
            continue
        game_ids.update(gl["Game_ID"].tolist())
        time.sleep(PAUSE)
    return sorted(game_ids)


def iter_line_scores(season):
    """Yield (game_id, line_score) for every game in a season.

    Games whose box score can't be fetched, or that come back without both
    teams, are skipped rather than aborting the crawl: a partial but real
    result beats no file at all.
    """
    for game_id in season_game_ids(season):
        time.sleep(PAUSE)

        line_score = fetch_line_score(game_id)
        if line_score is None or len(line_score) < 2:
            continue
        yield game_id, line_score

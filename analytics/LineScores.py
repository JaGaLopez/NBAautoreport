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
import pandas as pd
from nba_api.stats.endpoints import (
    boxscoresummaryv2,
    scoreboardv2,
    teamgamelog,
    teamgamelogs,
)

# BoxScoreSummaryV2 has a known data gap: from 2025-04-10 on, its LineScore rows
# come back with null quarter scores, which silently drops the last days of a
# season from every stat built on it. V3 has that data and is what nba_api's own
# warning points at, but it only exists from nba_api 1.11.4. Falling back keeps
# this module importable on an older install rather than failing the refresh.
try:
    from nba_api.stats.endpoints import boxscoresummaryv3

    HAS_V3 = True
except ImportError:  # nba_api < 1.11.4
    boxscoresummaryv3 = None
    HAS_V3 = False


# nba_api defaults to a 30s read timeout; stats.nba.com throttles datacenter
# IPs, so give each call more room and retry with exponential backoff.
TIMEOUT = 60

# Pause between calls, to stay under the throttle when running from a server IP.
PAUSE = 0.6

# V3 names the same fields differently. Mapping them back to the V2 spelling
# keeps the shape stable for every consumer of this module.
_V3_COLUMNS = {
    "teamId": "TEAM_ID",
    "teamTricode": "TEAM_ABBREVIATION",
    "period1Score": "PTS_QTR1",
    "period2Score": "PTS_QTR2",
    "period3Score": "PTS_QTR3",
    "period4Score": "PTS_QTR4",
    "score": "PTS",
}


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


def _from_v3(line_score, game_date):
    """Rewrite a V3 line score into the V2 column names callers expect.

    Returns None if the frame is missing the columns that matter, so a changed
    response shape reads as "couldn't fetch this game" rather than producing
    quietly wrong quarter scores.
    """
    if line_score is None or line_score.empty:
        return None
    if any(c not in line_score.columns for c in _V3_COLUMNS):
        return None

    out = line_score[list(_V3_COLUMNS)].rename(columns=_V3_COLUMNS)
    # V2 carried the date on every LineScore row; V3 keeps it on the game.
    out["GAME_DATE_EST"] = game_date
    return out


def _fetch_line_score_v3(game_id):
    summary = boxscoresummaryv3.BoxScoreSummaryV3(game_id=game_id, timeout=TIMEOUT)

    game_date = None
    try:
        info = summary.game_info.get_data_frame()
        if not info.empty and "gameDate" in info.columns:
            game_date = info.iloc[0]["gameDate"]
    except Exception:
        # The date only feeds a display string; losing it must not lose the game.
        pass

    return _from_v3(summary.line_score.get_data_frame(), game_date)


def fetch_line_score(game_id, retries=4, pause=1.0):
    """Fetch a game's line score, retrying transient nba_api failures.

    Returns a DataFrame in the V2 column shape (TEAM_ID, PTS_QTR1..4, PTS,
    TEAM_ABBREVIATION, GAME_DATE_EST), or None if it can't be fetched. A single
    dropped call (rate limit / timeout) is common when running from a server IP,
    and must not abort an entire season's worth of box scores.
    """
    for attempt in range(retries):
        try:
            if HAS_V3:
                return _fetch_line_score_v3(game_id)
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


def season_schedule(season):
    """(game_ids, dates) for a season, from a single league-wide call.

    One TeamGameLogs call covers all 30 teams, replacing the 30 per-team log
    calls this used to make.
    """
    logs = _retry(
        lambda: teamgamelogs.TeamGameLogs(
            season_nullable=season,
            season_type_nullable="Regular Season",
            timeout=TIMEOUT,
        ).get_data_frames()[0]
    )
    if logs is None or logs.empty:
        return set(), []

    game_ids = set(logs["GAME_ID"].tolist())
    dates = sorted(
        pd.to_datetime(logs["GAME_DATE"]).dt.strftime("%Y-%m-%d").unique()
    )
    return game_ids, dates


def fetch_day_line_scores(game_date, retries=4, pause=1.0):
    """Every line score for one calendar date, retrying transient failures.

    ScoreboardV2's LineScore already uses the same column names as the box
    score version, so callers need no translation.
    """
    for attempt in range(retries):
        try:
            return scoreboardv2.ScoreboardV2(
                game_date=game_date, timeout=TIMEOUT
            ).line_score.get_data_frame()
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(pause * 2 ** attempt)
    return None


def iter_line_scores(season):
    """Yield (game_id, line_score) for every game in a season.

    Walks the schedule one date at a time rather than one game at a time: a
    single scoreboard call returns every game played that day, which is about
    eight times fewer requests than fetching each box score. It also sidesteps
    the BoxScoreSummaryV2 gap, since the scoreboard reports quarter scores for
    the late-season dates that endpoint returns empty.

    Dates that can't be fetched, and games that come back without both teams,
    are skipped rather than aborting the crawl: a partial but real result beats
    no file at all.
    """
    game_ids, dates = season_schedule(season)

    for game_date in dates:
        time.sleep(PAUSE)

        day = fetch_day_line_scores(game_date)
        if day is None or day.empty or "GAME_ID" not in day.columns:
            continue

        for game_id, line_score in day.groupby("GAME_ID"):
            # A date can also carry games outside the regular season, so keep
            # only the ids the schedule actually listed.
            if game_id not in game_ids or len(line_score) < 2:
                continue
            yield game_id, line_score.reset_index(drop=True)


def iter_line_scores_by_game(season):
    """The old per-game crawl, kept for when a single game needs re-fetching.

    Slower by roughly eight times; iter_line_scores is the one the refresh uses.
    """
    for game_id in sorted(season_schedule(season)[0]):
        time.sleep(PAUSE)

        line_score = fetch_line_score(game_id)
        if line_score is None or len(line_score) < 2:
            continue
        yield game_id, line_score

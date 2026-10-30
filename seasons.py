"""The set of seasons the report covers, derived from the date.

One source of truth, imported by precompute (which decides what to build) and
by the Streamlit app (as a fallback when the API cannot be reached). These used
to be three hand-maintained lists, in the app, in precompute and in refresh.sh,
which silently disagreed the moment a new season started: the daily refresh kept
succeeding while building nothing new.

The authority on what the site can actually show is the API's /seasons route,
which lists what has been precomputed. This module only says what is worth
attempting.
"""

from datetime import date

# The earliest season the report covers. Seasons before this are not built.
FIRST_SEASON_START_YEAR = 2021

# An NBA season is named for the calendar year it starts in, and tips off in
# October. A date in October or later therefore belongs to the season starting
# that year; anything earlier belongs to the one that started the year before.
SEASON_START_MONTH = 10


def season_label(start_year):
    """2024 -> "2024-25"."""
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def current_start_year(today=None):
    """The start year of the season that is current on the given date."""
    today = today or date.today()
    return today.year if today.month >= SEASON_START_MONTH else today.year - 1


def all_seasons(today=None):
    """Every season to build, newest first.

    A season appears here from the moment its October arrives, which can be a
    few weeks before the first game. That is deliberate: precompute asks the API
    for its games and skips a season that has none yet, so the only cost of
    being early is one cheap call a day until the season tips off.
    """
    newest = current_start_year(today)
    return [season_label(y) for y in range(newest, FIRST_SEASON_START_YEAR - 1, -1)]

import os

import streamlit as st
import requests
import pandas as pd
import altair as alt
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
from st_aggrid.shared import JsCode

# Overridable so the app can be pointed at a locally running API during
# development; defaults to the deployed one.
API_URL = os.environ.get("NBA_API_URL", "https://nbastats.jglws.com")

# Newest first; also the set of seasons used for "historic low" comparisons.
SEASONS = ["2024-25", "2023-24", "2022-23", "2021-22"]

BASIC_COLS = {
    "TEAM_NAME": "Team",
    "FGM": "FG", "FGA": "FGA", "FG_PCT": "FG%",
    "FG3M": "3P", "FG3A": "3PA", "FG3_PCT": "3P%",
    "2P": "2P", "2PA": "2PA", "2P%": "2P%",
    "FTM": "FT", "FTA": "FTA", "FT_PCT": "FT%",
    "OREB": "ORB", "DREB": "DRB", "REB": "TRB",
    "AST": "AST", "STL": "STL", "BLK": "BLK",
    "TOV": "TOV", "PF": "PF", "PTS": "PTS",
}

ADV_COLS = {
    "TEAM_NAME": "Team",
    "OFF_RATING": "ORTG", "DEF_RATING": "DRTG", "NET_RATING": "NRTG",
    "TS_PCT": "TS%", "EFG_PCT": "eFG%",
    "AST_PCT": "AST%", "AST_TO": "AST/TO",
    "OREB_PCT": "ORB%", "DREB_PCT": "DRB%", "REB_PCT": "TRB%",
    "TM_TOV_PCT": "TOV%", "PACE": "PACE", "PIE": "PIE",
}

EFFORT_COMPONENT_LABELS = {
    "DEFLECTIONS": "Deflections",
    "CONTESTED_SHOTS": "Contested Shots",
    "LOOSE_BALLS_RECOVERED": "Loose Balls",
    "BOX_OUTS": "Box Outs",
    "CHARGES_DRAWN": "Charges Drawn",
    "SCREEN_ASSISTS": "Screen Assists",
    "OREB_PCT": "ORB%",
}

# Mirrors MIN_LEAD in analytics/GetHotStarts.py, which defines the stat.
MIN_LEAD = 5

# Mirrors MIN_PLAYER_ATTEMPTS in analytics/GetThreePointShooting.py.
MIN_PLAYER_ATTEMPTS = 100

# Shortest first, so "recent form" reads from the tightest window that has games.
SHOOTING_WINDOWS = ("1 Week", "2 Weeks", "3 Weeks")

BASIC_LOWER_IS_BETTER = {"TOV", "PF"}
ADV_LOWER_IS_BETTER   = {"DRTG", "TOV%"}

PERCENTILE_STYLE = JsCode("""
function(params) {
    if (params.colDef.field === 'Metric') return null;
    if (!params.data || params.data.Metric !== 'Percentile') return null;
    var val = parseFloat(params.value);
    if (isNaN(val)) return null;
    if (val >= 80) return {backgroundColor: '#27ae60', color: 'white'};
    if (val >= 60) return {backgroundColor: '#a8e6cf', color: 'black'};
    if (val >= 40) return {backgroundColor: '#e8e8e8', color: 'black'};
    if (val >= 20) return {backgroundColor: '#ffb3b3', color: 'black'};
    return {backgroundColor: '#e74c3c', color: 'white'};
}
""")

DOUBLE_CLICK_JS = JsCode("function(e){ e.node.setSelected(true); }")


# Center both the header label and the cell text. AG Grid aligns headers with
# flexbox and cells with text-align, so it takes both rules.
CENTERED_CSS = {
    ".ag-header-cell-label": {"justify-content": "center"},
    ".ag-cell": {"text-align": "center"},
}


def show_table(df, *, double_click=False, cell_style=None, height=None,
               pre_selected=None):
    gb = GridOptionsBuilder.from_dataframe(df)
    # suppressColumnVirtualisation so every column (even off-screen ones on wide
    # tables) gets measured and autosized to its content.
    gb.configure_grid_options(suppressMovableColumns=True, suppressColumnVirtualisation=True)

    if cell_style is not None:
        gb.configure_default_column(resizable=True, sortable=False, cellStyle=cell_style)
    else:
        gb.configure_default_column(resizable=True, sortable=True)

    if double_click:
        # pre_selected re-applies the shared selection on every rerun, so both
        # tables highlight the same team instead of each keeping its own.
        gb.configure_selection(
            selection_mode="single",
            use_checkbox=False,
            pre_selected_rows=pre_selected or [],
        )
        gb.configure_grid_options(
            suppressRowClickSelection=True,
            onRowDoubleClicked=DOUBLE_CLICK_JS,
        )

    go = gb.build()

    no_filter = {
        "filter": False,
        "suppressMenu": True,
        "suppressHeaderFilterButton": True,
        "suppressHeaderMenuButton": True,
    }
    go.setdefault("defaultColDef", {}).update(no_filter)

    # Just suppress the filter UI per column; widths are handled by AG Grid's
    # autoSizeStrategy below, which grows/shrinks each column to fit its longest
    # entry instead of a hand-rolled width estimate.
    for col in go.get("columnDefs", []):
        col.update(no_filter)

    # fitCellContents = size every column to its content (header + longest
    # cell), letting the wide stats tables scroll sideways.
    go["autoSizeStrategy"] = {"type": "fitCellContents"}

    kwargs = dict(
        gridOptions=go,
        allow_unsafe_jscode=True,
        custom_css=CENTERED_CSS,
        update_mode=GridUpdateMode.SELECTION_CHANGED if double_click else GridUpdateMode.NO_UPDATE,
    )
    if height is not None:
        kwargs["height"] = height

    return AgGrid(df, **kwargs)


def simple_table(df, height=None):
    """A small read-only table for the narrative cards.

    Deliberately native rather than AG Grid: a grid first drawn inside a
    collapsed expander lays out at zero width and stays blank when opened, and
    no resize hook recovers it. st.dataframe re-renders on expand.
    """
    st.dataframe(df, hide_index=True, use_container_width=True, height=height)


def round_for_display(df):
    """Round numeric columns to a readable precision based on their magnitude."""
    for col in df.columns:
        if col == "Team" or not pd.api.types.is_numeric_dtype(df[col]):
            continue
        m = df[col].abs().max()
        if m <= 1:      # fractions / percentages (e.g. 0.553)
            df[col] = df[col].round(3)
        elif m <= 10:   # ratios (e.g. 1.91)
            df[col] = df[col].round(2)
        else:           # counting stats / ratings (e.g. 54.1)
            df[col] = df[col].round(1)
    return df


@st.cache_data(ttl=86400)
def load_data(season):
    basic_resp  = requests.get(f"{API_URL}/teams/{season}")
    adv_resp    = requests.get(f"{API_URL}/teams/{season}/advanced")
    weekly_resp = requests.get(f"{API_URL}/teams/{season}/weekly-netrating")

    # The core datasets must all be present. If any is still being precomputed
    # the API returns a 503 error payload (a scalar dict); signal the caller
    # rather than letting pd.DataFrame choke on it and crash the whole page.
    if not (basic_resp.ok and adv_resp.ok and weekly_resp.ok):
        return None

    basic_raw = pd.DataFrame(basic_resp.json())
    adv_raw   = pd.DataFrame(adv_resp.json())
    weekly    = weekly_resp.json()

    # Comebacks are a newer dataset; tolerate it not being precomputed yet.
    # None signals "unavailable" so the UI can distinguish a missing file from
    # a team that genuinely had zero comebacks.
    cb_resp   = requests.get(f"{API_URL}/teams/{season}/comebacks")
    comebacks = cb_resp.json() if cb_resp.ok else None

    # Same deal for effort-while-losing. It additionally comes back empty for
    # pre-2015-16 seasons, which have no NBA hustle tracking to build it from.
    ef_resp = requests.get(f"{API_URL}/teams/{season}/effort-while-losing")
    effort  = ef_resp.json() if ef_resp.ok else None

    hs_resp = requests.get(f"{API_URL}/teams/{season}/hot-starts")
    hot_starts = hs_resp.json() if hs_resp.ok else None

    sv_resp = requests.get(f"{API_URL}/teams/{season}/shooting-variance")
    shooting = sv_resp.json() if sv_resp.ok else None

    tp_resp = requests.get(f"{API_URL}/teams/{season}/three-point-shooting")
    threes = tp_resp.json() if tp_resp.ok else None

    pf_resp = requests.get(f"{API_URL}/teams/{season}/profiles")
    profiles = pf_resp.json() if pf_resp.ok else None

    basic_raw["2P"]  = basic_raw["FGM"] - basic_raw["FG3M"]
    basic_raw["2PA"] = basic_raw["FGA"] - basic_raw["FG3A"]
    basic_raw["2P%"] = basic_raw["2P"] / basic_raw["2PA"]

    basic_df = basic_raw[[c for c in BASIC_COLS if c in basic_raw.columns]].rename(columns=BASIC_COLS)
    adv_df   = adv_raw[[c for c in ADV_COLS if c in adv_raw.columns]].rename(columns=ADV_COLS)

    return (
        round_for_display(basic_df),
        round_for_display(adv_df),
        weekly,
        comebacks,
        effort,
        hot_starts,
        shooting,
        threes,
        profiles,
    )


def selected_team_from(result):
    """Extract the selected team name from an AgGrid result, or None."""
    rows = result["selected_rows"]
    if rows is None:
        return None
    if hasattr(rows, "iloc") and len(rows) > 0:
        return rows.iloc[0]["Team"]
    if isinstance(rows, list) and len(rows) > 0:
        return rows[0]["Team"]
    return None


def build_comparison(df, team_name, lower_is_better_set):
    stat_cols = [
        c for c in df.columns
        if c != "Team" and pd.api.types.is_numeric_dtype(df[c])
    ]
    team_row  = df[df["Team"] == team_name][stat_cols].iloc[0]
    avg       = df[stat_cols].mean().round(2)
    delta     = (team_row - avg).round(2)

    pcts = {}
    for col in stat_cols:
        val      = team_row[col]
        all_vals = df[col].dropna()
        pct      = round((all_vals < val).sum() / len(all_vals) * 100, 1)
        if col in lower_is_better_set:
            pct = round(100 - pct, 1)
        pcts[col] = pct

    comp = pd.DataFrame(
        [team_row, avg, delta, pd.Series(pcts)],
        index=[team_name, "League Average", "Delta", "Percentile"],
    )
    comp.index.name = "Metric"
    return comp.reset_index()


@st.cache_data(ttl=86400)
def team_comeback_counts(team_name):
    """This team's comeback count in every season we have data for: {season: count}.
    Used to flag a season that's a historic low across our dataset."""
    counts = {}
    for s in SEASONS:
        resp = requests.get(f"{API_URL}/teams/{s}/comebacks")
        if not resp.ok:
            continue
        info = (resp.json().get("teams", {}) or {}).get(team_name)
        if info is not None:
            counts[s] = info.get("count", 0)
    return counts


def tech_note(text):
    """A technical blurb: what the metric means and how to read it.

    Gray, so the definitions sit back from the observations about the team.
    """
    st.caption(text)


def insight(text):
    """An observation about this particular team, in body white.

    These carry the actual news on the card, so they read at full weight while
    the tech_note definitions stay gray behind them.
    """
    st.markdown(
        f"<p style='font-size:0.9rem; margin:0.25rem 0 0.5rem 0;'>{text}</p>",
        unsafe_allow_html=True,
    )


# Streamlit's own delta colors, reused so hand-rolled bubbles match the ones
# st.metric renders on the other cards.
_BUBBLE_GREEN = "rgb(9, 171, 59)"
_BUBBLE_RED = "rgb(255, 43, 43)"
_BUBBLE_GREEN_BG = "rgba(9, 171, 59, 0.2)"
_BUBBLE_RED_BG = "rgba(255, 43, 43, 0.2)"


def bubbles(items):
    """Render delta-style pills: [(text, good_or_bad), ...].

    st.metric only takes one delta, and it picks the arrow direction from the
    sign of the string, so "Streaky" can't point down without literally showing
    a minus. Rendering the pills directly gives both the second bubble and the
    arrow that actually matches the meaning.
    """
    spans = []
    for text, good in items:
        color = _BUBBLE_GREEN if good else _BUBBLE_RED
        background = _BUBBLE_GREEN_BG if good else _BUBBLE_RED_BG
        arrow = "&#8593;" if good else "&#8595;"
        spans.append(
            f"<span style='color:{color}; background-color:{background}; "
            f"font-size:0.875rem; padding:0.15rem 0.6rem; border-radius:0.5rem; "
            f"margin-right:0.5rem; white-space:nowrap; display:inline-block;'>"
            f"{arrow} {text}</span>"
        )
    st.markdown(
        f"<div style='margin:-0.5rem 0 0.5rem 0;'>{''.join(spans)}</div>",
        unsafe_allow_html=True,
    )


def render_comeback_narrative(team_name, team_count, league_avg, games):
    """Render the 4th-quarter-comebacks narrative: the team's total vs. the league
    average (the metric's arrow shows the gap), with a historic-low note and the
    team's comeback games."""
    gap = round(team_count - league_avg, 1)
    st.metric(
        "Total Comebacks",
        f"{team_count} vs. {round(league_avg, 1)} (League Average)",
    )
    bubbles([(f"{gap:+.1f}", gap >= 0)])
    # Rendered only when asked for. Both AG Grid and st.dataframe
    # lay out at zero size if they are first drawn inside a collapsed
    # container and never recover, so the body must not exist until
    # it is actually shown.
    if st.toggle("Details", key=f"details-comebacks-{team_name}"):

        history = team_comeback_counts(team_name)
        if len(history) > 1:
            lo, hi = min(history.values()), max(history.values())
            if team_count == lo < hi:
                insight(
                    f"Historic low: fewest comebacks for {team_name} "
                    f"in our {len(history)} seasons of data."
                )

        if games:
            # Biggest comeback this season: the largest Q3 deficit this team erased.
            biggest = max(games, key=lambda g: g["DEFICIT_AFTER_Q3"])
            big_opp = biggest["MATCHUP"].split("vs.")[-1].strip()
            insight(
                f"Biggest comeback this season: "
                f"{biggest['DEFICIT_AFTER_Q3']}-pt deficit vs. {big_opp}."
            )

            games_df = pd.DataFrame(games)
            games_df["Date"] = pd.to_datetime(games_df["GAME_DATE"]).dt.strftime("%m/%d")
            # Strip the selected team's own abbreviation, leaving just the opponent.
            games_df["Opponent"] = games_df["MATCHUP"].str.split("vs.").str[-1].str.strip()
            games_df = games_df[
                ["Date", "Opponent", "DEFICIT_AFTER_Q3", "FINAL_TEAM", "FINAL_OPP"]
            ].rename(columns={
                "DEFICIT_AFTER_Q3": "Q3 Deficit",
                "FINAL_TEAM": "Final",
                "FINAL_OPP": "Final (Opp)",
            })
            simple_table(games_df, height=175)

        tech_note(
            "A comeback is trailing after three quarters and still winning the game."
        )


@st.cache_data(ttl=86400)
def team_effort_history(team_name):
    """This team's effort-retention score in every season we have: {season: score}."""
    scores = {}
    for s in SEASONS:
        resp = requests.get(f"{API_URL}/teams/{s}/effort-while-losing")
        if not resp.ok:
            continue
        info = (resp.json().get("teams", {}) or {}).get(team_name)
        if info is not None and info.get("effort_retention") is not None:
            scores[s] = info["effort_retention"]
    return scores


def render_effort_narrative(team_name, info, league_avg, scored=None):
    """Render the effort-while-losing narrative: how much of its hustle a team
    keeps in losses relative to its own wins, vs. the league average."""
    score = info["effort_retention"]


    gap = (score - league_avg) * 100
    st.metric(
        "Effort While Losing",
        f"{score:.0%} vs. {league_avg:.0%} (League Average)",
    )
    bubbles([(f"{gap:+.0f} pts", gap >= 0)])
    # Rendered only when asked for. Both AG Grid and st.dataframe
    # lay out at zero size if they are first drawn inside a collapsed
    # container and never recover, so the body must not exist until
    # it is actually shown.
    if st.toggle("Details", key=f"details-effort-{team_name}"):

        # Flag a season that is (or ties) this team's lowest across our data. Only
        # meaningful with more than one season and scores that actually vary.
        history = team_effort_history(team_name)
        if len(history) > 1:
            lo, hi = min(history.values()), max(history.values())
            if score == lo < hi:
                insight(
                    f"Historic low, least effort in losses for {team_name} "
                    f"in our {len(history)} seasons of data."
                )

        components = info.get("components") or {}
        if components:
            # Kept numeric (not a "%" string) so the grid still sorts these properly.
            comp_df = pd.DataFrame(
                [
                    {"Metric": EFFORT_COMPONENT_LABELS.get(k, k),
                     "% of Winning Effort": round(v * 100)}
                    for k, v in components.items()
                ]
            ).sort_values("% of Winning Effort")
            simple_table(comp_df, height=175)

        tech_note(
            "100% means they compete equally hard whether winning or losing, "
            "below 100% means the effort drops off once games go bad."
        )
        # Sparse components are shown but not scored, so say which ones.
        if scored:
            unscored = [EFFORT_COMPONENT_LABELS.get(c, c)
                        for c in (info.get("components") or {}) if c not in scored]
            if unscored:
                tech_note(
                    f"{', '.join(unscored)} shown for context but left out of the "
                    "score: teams don't draw enough charges while losing for the "
                    "ratio to mean anything."
                )


def render_hot_starts_narrative(team_name, info, league_avg):
    """Render the hot-starts narrative: how often a team leads after one
    quarter, and whether that early lead actually survives to halftime."""
    q1_pct = info["q1_lead_pct"]

    gap = (q1_pct - league_avg) * 100
    st.metric(
        "Hot Starts",
        f"{q1_pct:.0%} vs. {league_avg:.0%} (League Average)",
    )
    bubbles([(f"{gap:+.0f} pts", gap >= 0)])
    # Rendered only when asked for. Both AG Grid and st.dataframe
    # lay out at zero size if they are first drawn inside a collapsed
    # container and never recover, so the body must not exist until
    # it is actually shown.
    if st.toggle("Details", key=f"details-hotstarts-{team_name}"):

        # First quarter and halftime read as two separate observations: how often
        # the start happens, then what becomes of it.
        insight(
            f"First quarter: {team_name} led by {MIN_LEAD}+ after one quarter in "
            f"{q1_pct:.0%} of its games ({info['q1_leads']} of {info['games']})."
        )

        held_pct = info.get("held_pct")
        if held_pct is not None:
            kept = "kept" if held_pct >= 0.5 else "gave back"
            insight(
                f"Halftime: it {kept} the start, carrying a lead at least that big "
                f"into halftime in {held_pct:.0%} of them "
                f"({info['held']} of {info['q1_leads']})."
            )

        def _row(label, games, win_pct, lift, vs_league):
            return {
                "Split": label,
                "Games": games,
                "Win%": round(win_pct * 100) if win_pct is not None else None,
                "vs Season": lift,
                "vs League": vs_league,
            }

        starts_df = pd.DataFrame([
            _row(f"Lead by {MIN_LEAD}+ after Q1", info["q1_leads"],
                 info.get("q1_win_pct"), info.get("q1_win_lift"),
                 info.get("q1_win_lift_vs_league")),
            _row("Held or increased lead after first half", info.get("held"),
                 info.get("held_win_pct"), info.get("held_win_lift"),
                 info.get("held_win_lift_vs_league")),
        ])
        # Older stored data has no win columns; drop them rather than showing
        # a table of blanks.
        simple_table(starts_df.dropna(axis=1, how="all"), height=140)

        tech_note(
            "Win% is how often the team won those games. vs Season is how much "
            "higher that is than its win rate overall, and vs League compares "
            "that gain to the average team's: every team wins more when ahead, "
            "so the gain is what separates them."
        )
        tech_note(
            f"A start counts only at {MIN_LEAD} points or more, since a one-point "
            "edge after twelve minutes is noise. Held means the halftime lead was "
            "at least as big as the first-quarter one, so a start that gets "
            "whittled away doesn't count."
        )


def _ordinal(n):
    """83 -> '83rd'. Percentiles read as ordinals, and "83th" is jarring.

    None in means None out: a caller with no number to show must leave the
    phrase out rather than print "None percentile".
    """
    if n is None:
        return None
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _fgm_band(mean, spread):
    """A one-standard-deviation band of made shots, as a "38-45" string."""
    if mean is None or spread is None:
        return None
    return f"{round(mean - spread)}-{round(mean + spread)}"


def streak_insight(team_name, streaks):
    """Run lengths, and what usually follows a game on the current side.

    For most teams this lands near a coin flip, which is the honest answer, so
    the wording only claims a lean when the base rate actually shows one.
    """
    if not streaks or streaks.get("repeat_pct") is None:
        return

    direction = streaks["current_direction"]
    repeat = streaks["repeat_pct"]
    if repeat >= 0.55:
        outlook = f"the next one leans {direction} at {repeat:.0%}"
    elif repeat <= 0.45:
        outlook = (
            f"the next one actually leans "
            f"{'cold' if direction == 'hot' else 'hot'} at {1 - repeat:.0%}"
        )
    else:
        outlook = f"the next one is close to a coin flip at {repeat:.0%}"

    insight(
        f"Hot and cold runs last {streaks['avg_length']} games on average "
        f"(longest {streaks['longest']}). {team_name} is on a "
        f"{streaks['current_length']}-game {direction} run, and historically "
        f"{outlook}."
    )


def render_shooting_variance_narrative(team_name, info, league_avg, as_of):
    """Render the shooting-variance narrative: the band of made shots a team
    lands in on a typical night against the league's, whether that band is
    streaky or steady, and how the last one, two, and three weeks compare."""
    stdev = info.get("efg_stdev")
    base = info.get("baseline") or {}

    band = _fgm_band(base.get("fgm"), base.get("fgm_stdev"))
    efg = base.get("efg_pct")

    # Season-wide headline: the efficiency, with the band of makes it usually
    # produces. Older stored data predates the FGM fields, so fall back to the
    # efficiency alone rather than dropping the title and headline entirely.
    if efg is not None and band:
        headline = f"{efg:.1%} eFG% ({band} FGM)"
    elif efg is not None:
        headline = f"{efg:.1%} eFG%"
    else:
        headline = "Not available"

    st.metric("Shooting Variance", headline)


    pills = []
    if stdev is not None:
        streaky = stdev > league_avg
        pills.append(("Streaky" if streaky else "Stable", not streaky))

    # Recent form comes from the shortest window available, falling back to the
    # direction of the run the team is currently on.
    windows = info.get("windows") or {}
    streaks = info.get("streaks") or {}
    recent = next((windows[label] for label in SHOOTING_WINDOWS if label in windows), None)
    if recent is not None and recent.get("efg_delta_pts") is not None:
        hot = recent["efg_delta_pts"] >= 0
        pills.append((f"Recently: {'Hot' if hot else 'Cold'}", hot))
    elif streaks.get("current_direction"):
        hot = streaks["current_direction"] == "hot"
        pills.append((f"Recently: {'Hot' if hot else 'Cold'}", hot))

    if pills:
        bubbles(pills)
    # Rendered only when asked for. Both AG Grid and st.dataframe
    # lay out at zero size if they are first drawn inside a collapsed
    # container and never recover, so the body must not exist until
    # it is actually shown.
    if st.toggle("Details", key=f"details-shooting-{team_name}"):

        # What the season says to expect, before looking at the recent form below.
        if base.get("efg_pct") is not None:
            expected = (
                f"Expected: {base['efg_pct']:.1%} eFG% on {base['fga']:.0f} attempts "
                f"per game, {_ordinal(base['efg_percentile'])} percentile in the league."
            )
            if base.get("open_share") is not None:
                expected += (
                    f" {base['open_share']:.0%} of those looks are open or wide open "
                    f"({_ordinal(base['open_share_percentile'])} percentile), and they shoot "
                    f"{base['open_efg_pct']:.1%} on them."
                )
            insight(expected)

        if windows:
            rows = []
            for label, w in windows.items():
                delta = w["efg_delta_pts"]
                rows.append({
                    "Window": label,
                    "Games": w["games"],
                    "eFG%": round(w["efg_pct"] * 100, 1),
                    # Absent on data stored before this field existed. Dropped
                    # below rather than rendered as an empty column.
                    "FGM vs. Avg": w.get("fgm_delta"),
                    "Swings": w.get("swings"),
                    "Form": "Hot" if delta >= 0 else "Cold",
                })
            windows_df = pd.DataFrame(rows).dropna(axis=1, how="all")
            simple_table(windows_df, height=140)

        streak_insight(team_name, streaks)

        if as_of:
            insight(f"Through games of {as_of}.")

        tech_note(
            "Season eFG% with the range of made shots (one std). Streaky or "
            "stable is set by week-to-week swing in eFG%, in points, against the "
            "league average."
        )
        if windows:
            tech_note(
                "Swings are a personalized stat, how far a team is off their own "
                "baseline. 1 is normal, 0 is cold, 2 is hot, past those is more extreme."
            )


def render_three_point_shooting_narrative(team_name, info, league, prior_season, as_of):
    """Render the three-point overview: how much a team shoots from deep, how
    well, how that compares to last season, and who is actually taking them."""
    fg3a = info.get("fg3a")
    pct = info.get("fg3_pct")

    if fg3a is not None and pct is not None:
        headline = f"{fg3a:.1f} 3PA per game at {pct:.1%}"
    elif pct is not None:
        headline = f"{pct:.1%} from three"
    else:
        headline = "Not available"

    st.metric("3PT Shooting", headline)

    # Volume and accuracy against the league, then the direction of travel
    # against this team's own last season.
    pills = []
    league_fg3a = (league or {}).get("fg3a")
    if fg3a is not None and league_fg3a:
        heavy = fg3a >= league_fg3a
        pills.append(("High Volume" if heavy else "Low Volume", heavy))

    change = info.get("change") or {}
    if change.get("fg3a") is not None:
        more = change["fg3a"] >= 0
        pills.append((f"{'More' if more else 'Fewer'} than last year", more))

    if pills:
        bubbles(pills)
    # Rendered only when asked for. Both AG Grid and st.dataframe
    # lay out at zero size if they are first drawn inside a collapsed
    # container and never recover, so the body must not exist until
    # it is actually shown.
    if st.toggle("Details", key=f"details-threes-{team_name}"):

        rate = info.get("fg3a_rate")
        if rate is not None:
            line = (
                f"Threes are {rate:.0%} of everything they shoot, "
                f"{_ordinal(info['fg3a_percentile'])} percentile in volume and "
                f"{_ordinal(info['fg3_pct_percentile'])} in accuracy."
            )
            insight(line)

        prior = info.get("prior")
        if prior and change and prior_season:
            vol = change["fg3a"]
            acc = change["fg3_pct_pts"]
            insight(
                f"Against {prior_season}: {abs(vol):.1f} {'more' if vol >= 0 else 'fewer'} "
                f"attempts a game (from {prior['fg3a']:.1f}), and "
                f"{abs(acc):.1f} points {'better' if acc >= 0 else 'worse'} at "
                f"{pct:.1%} against {prior['fg3_pct']:.1%}."
            )

        shooters = info.get("shooters") or []
        if shooters:
            rows = [{
                "Shooter": s["name"],
                "3PA": s["fg3a"],
                "3P%": round(s["fg3_pct"] * 100, 1),
                "Made": s["fg3m"],
                "Swing": s.get("fg3m_stdev"),
                "Blanks": round(s["blank_pct"] * 100),
            } for s in shooters]
            simple_table(pd.DataFrame(rows).dropna(axis=1, how="all"), height=175)

        if as_of:
            insight(f"Through games of {as_of}.")

        tech_note(
            "Team volume and accuracy from three, against the league and against "
            "this team last season. Volume moves fast league-wide, so the "
            "year-over-year comparison says more about intent than the league rank."
        )
        if shooters:
            tech_note(
                f"Shooters are the most accurate on the roster with at least "
                f"{MIN_PLAYER_ATTEMPTS} attempts on the season. Swing is how much "
                "their makes move night to night, and Blanks is the share of games "
                "they made none at all: two players at the same percentage can be "
                "very different to rely on."
            )



# Standard three-letter codes, so the scatter can label points without crowding.
TEAM_CODES = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "LA Clippers": "LAC", "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM", "Miami Heat": "MIA", "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


def render_efficiency_landscape(adv_df, selected_team):
    """Offense against defense, as a four-quadrant scatter of the whole league.

    Defensive rating is inverted so that up and to the right is good on both
    axes: the top-right quadrant is teams that score well and stop teams, the
    bottom-left is neither. The dashed crosshair sits at the league average, so
    a team's quadrant is read against the league rather than against zero.
    """
    needed = {"Team", "ORTG", "DRTG"}
    if not needed.issubset(adv_df.columns):
        return

    df = adv_df[["Team", "ORTG", "DRTG"]].dropna().copy()
    if df.empty:
        return

    df["NRTG"] = (df["ORTG"] - df["DRTG"]).round(1)
    df["Code"] = df["Team"].map(TEAM_CODES).fillna(df["Team"].str[:3].str.upper())
    df["Selected"] = df["Team"] == selected_team

    mean_o = float(df["ORTG"].mean())
    mean_d = float(df["DRTG"].mean())

    # Pad each axis so no team is pinned to an edge, and so the crosshair is
    # never flush against the plot border.
    pad_o = max(1.5, (df["ORTG"].max() - df["ORTG"].min()) * 0.10)
    pad_d = max(1.5, (df["DRTG"].max() - df["DRTG"].min()) * 0.10)
    x = alt.X(
        "ORTG:Q", title="Offensive Efficiency",
        # zero=False: ratings live near 110, so including the origin would
        # squash all thirty teams into one corner.
        scale=alt.Scale(domain=[df["ORTG"].min() - pad_o, df["ORTG"].max() + pad_o],
                        nice=False, zero=False),
    )
    # reverse=True puts the best defense at the top, matching the good/good corner.
    y = alt.Y(
        "DRTG:Q", title="Defensive Efficiency",
        scale=alt.Scale(domain=[df["DRTG"].min() - pad_d, df["DRTG"].max() + pad_d],
                        nice=False, zero=False, reverse=True),
    )

    tooltip = [
        alt.Tooltip("Team:N"), alt.Tooltip("ORTG:Q", format=".1f"),
        alt.Tooltip("DRTG:Q", format=".1f"), alt.Tooltip("NRTG:Q", format="+.1f"),
    ]

    points = alt.Chart(df).mark_circle(size=170, opacity=0.85).encode(
        x=x, y=y, tooltip=tooltip,
        color=alt.condition(
            alt.datum.Selected,
            alt.value("#ff4b4b"),
            alt.Color("NRTG:Q", title="Net",
                      scale=alt.Scale(scheme="blueorange", domainMid=0)),
        ),
    )
    labels = alt.Chart(df).mark_text(
        align="left", dx=9, dy=3, fontSize=10, color="#cccccc",
    ).encode(x=x, y=y, text="Code:N")

    crosshair_v = alt.Chart(pd.DataFrame({"v": [mean_o]})).mark_rule(
        strokeDash=[4, 4], color="#888888").encode(x="v:Q")
    crosshair_h = alt.Chart(pd.DataFrame({"v": [mean_d]})).mark_rule(
        strokeDash=[4, 4], color="#888888").encode(y="v:Q")

    chart = (
        (crosshair_v + crosshair_h + points + labels)
        .properties(width="container", height=460, padding={"bottom": 20})
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(chart, use_container_width=True)



def _percentile_of(entry, teams=30):
    """Percentile for a rank entry.

    Payloads written before the percentile field existed carry only `rank`, so
    derive it rather than rendering the card blank: rank 1 of 30 is the 100th
    percentile, rank 30 the 0th.
    """
    pct = entry.get("percentile")
    if pct is not None:
        return pct
    rank = entry.get("rank")
    if rank is None or teams < 2:
        return None
    return round((teams - rank) / (teams - 1) * 100)


def _rank_rows(ranks):
    """Percentile only: the raw value is the same number already on the big
    tables, and standing is what the card is for."""
    return [{"Stat": r["stat"], "Percentile": _percentile_of(r)} for r in ranks]


def _play_rows(plays, type_label, freq_label, ppp_label):
    return [{
        type_label: p["type"],
        freq_label: f"{p['freq']:.0%}",
        ppp_label: round(p["ppp"], 2) if p.get("ppp") is not None else None,
        "Pctile": p.get("percentile"),
    } for p in plays]


def _headline_rank(ranks, stat):
    """The (value, percentile) pair for one named stat, or (None, None)."""
    for r in ranks:
        if r["stat"] == stat:
            return r.get("value"), _percentile_of(r)
    return None, None


def render_offensive_overview_narrative(team_name, info):
    """Render the offensive overview: how the team's offense ranks, and what
    it runs. Offense only; the defensive counterpart is its own card."""
    ranks = info.get("ranks") or []
    plays = info.get("play_types") or []

    value, pct = _headline_rank(ranks, "Offensive Rating")
    if value is None:
        headline = "Not available"
    elif pct is None:
        headline = f"{value:.1f} Offensive Rating"
    else:
        headline = f"{value:.1f} Offensive Rating ({_ordinal(pct)} percentile)"
    st.metric("Offensive Overview", headline)

    if pct is not None:
        bubbles([(f"{_ordinal(pct)} percentile offense", pct >= 50)])

    if st.toggle("Details", key=f"details-offense-{team_name}"):
        if plays:
            top = plays[0]
            insight(
                f"Most of what they run is {top['type'].lower()} at "
                f"{top['freq']:.0%} of possessions, scoring {top['ppp']:.2f} "
                f"points per play ({_ordinal(top['percentile'])} percentile)."
            )
        if ranks:
            simple_table(pd.DataFrame(_rank_rows(ranks)), height=250)
        if plays:
            simple_table(
                pd.DataFrame(_play_rows(plays, "Play Type", "Run", "Points/Play")),
                height=250
            )

        tech_note(
            "Percentile against the other 29 teams, where 100 is best. "
            "Turnovers count down, so fewest is the 100th percentile; every "
            "other stat here counts up."
        )
        if plays:
            tech_note(
                "Run is the share of this team's possessions ending in that "
                "action, with what it produces and how that compares league wide."
            )


def render_defensive_formations_narrative(team_name, info):
    """Render the defensive overview: how the defense ranks, and what opponents
    run against it. Defense only; offense is its own card."""
    ranks = info.get("ranks") or []
    plays = info.get("play_types") or []

    value, pct = _headline_rank(ranks, "Defensive Rating")
    if value is None:
        headline = "Not available"
    elif pct is None:
        headline = f"{value:.1f} Defensive Rating"
    else:
        headline = f"{value:.1f} Defensive Rating ({_ordinal(pct)} percentile)"
    st.metric("Defensive Formations", headline)

    if pct is not None:
        bubbles([(f"{_ordinal(pct)} percentile defense", pct >= 50)])

    if st.toggle("Details", key=f"details-defense-{team_name}"):
        if plays:
            top = plays[0]
            insight(
                f"Opponents come at them mostly with {top['type'].lower()} at "
                f"{top['freq']:.0%} of possessions, scoring {top['ppp']:.2f} "
                f"points per play against them."
            )
        if ranks:
            simple_table(pd.DataFrame(_rank_rows(ranks)), height=250)
        if plays:
            simple_table(
                pd.DataFrame(
                    _play_rows(plays, "Defending Against", "Faced",
                               "Points Allowed")
                ),
                height=250,
            )

        tech_note(
            "Percentile against the other 29 teams, where 100 is best: fewest "
            "opponent points, lowest opponent percentages, most steals, blocks "
            "and forced turnovers."
        )
        if plays:
            tech_note(
                "Faced is the share of opponent possessions ending in that "
                "action against this team. The API exposes no zone or man "
                "coverage split, so scheme has to be inferred from what "
                "opponents lean on and where the defense holds up."
            )


# Page setup 
st.set_page_config(layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] > div:nth-child(2) {
        border-left: 2px solid #cccccc;
        padding-left: 2rem;
    }
    /* Narrative cards: the stat's name is the headline, so scale the metric
       label up and the value down. The value line now carries the "vs. League
       Avg" comparison text, which is too long for the default 2.25rem. */
    [data-testid="stMetricLabel"] p { font-size: 1.25rem; font-weight: 600; }
    /* Details toggle: white track with a dark knob when on, instead of the
       default red. first-of-type picks the switch itself; the label text sits
       in a sibling div that must keep its own background. */
    [data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type {
        background-color: #fafafa !important;
    }
    [data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type > div {
        background-color: #0e1117 !important;
    }
    [data-testid="stMetricValue"]   { font-size: 1.6rem; }
</style>
""", unsafe_allow_html=True)

st.markdown("<h1 style='text-align: center;'>NBA Team Stats</h1>", unsafe_allow_html=True)

# Section headers row
head_left, head_right = st.columns(2)
with head_left:
    st.subheader("All Teams")
with head_right:
    st.subheader("Food for Thought")

# Dropdowns row (under their respective headers)
sel_left, sel_right = st.columns(2)
with sel_left:
    season = st.selectbox("Season", SEASONS)
with sel_right:
    view = st.selectbox("View", ["Narratives", "Stats"])

with st.spinner("Loading stats..."):
    data = load_data(season)

if data is None:
    st.warning(f"Stats for {season} haven't been precomputed yet. Try another season.")
    st.stop()

basic_df, adv_df, weekly, comebacks, effort, hot_starts, shooting, threes, profiles = data

# Layout
# One column pair, with each side stacking its own content. Two separate
# st.columns() rows would align the second row across both sides, leaving a gap
# under the basic table whenever the narratives column is taller.
left, right = st.columns(2)

def row_of(df, team_name):
    """Row ids to pre-select for a team, as AG Grid expects them.

    These land in gridOptions initialState.rowSelection, which matches on row
    id rather than position. Without a getRowId the ids are the row index as a
    string, so an int here silently matches nothing.
    """
    if not team_name:
        return []
    teams = list(df["Team"])
    return [str(teams.index(team_name))] if team_name in teams else []


# Both tables render pre-selected on the team chosen last run, so a new pick on
# one table clears the stale highlight on the other instead of leaving two rows
# lit at once.
active_team = st.session_state.get("selected_team")

# Render the two selectable source tables first (both double-clickable)
with left:
    st.caption("Per Game Stats")
    basic_result = show_table(basic_df, double_click=True,
                              pre_selected=row_of(basic_df, active_team))

    st.caption("Advanced Stats")
    adv_result = show_table(adv_df, double_click=True,
                            pre_selected=row_of(adv_df, active_team))

# Figure out which table the user most recently clicked. Both tables come in
# pre-selected on active_team, so a table reporting anything else is the one
# just clicked. That is the whole rule, no per-table history needed.
basic_sel = selected_team_from(basic_result)
adv_sel   = selected_team_from(adv_result)

if basic_sel is not None and basic_sel != active_team:
    selected_team = basic_sel
elif adv_sel is not None and adv_sel != active_team:
    selected_team = adv_sel
else:
    selected_team = active_team or basic_sel or adv_sel

st.session_state["selected_team"] = selected_team

# The tables above were drawn pre-selected on the previous team, so when the
# pick changes they need one more pass to move the highlight. This settles
# immediately: after the rerun the tables agree with active_team and no further
# rerun is requested.
if selected_team != active_team:
    st.rerun()

# Now render the comparison tables on the right
with right:
    if view == "Narratives":
        st.caption("Narratives")
        if not selected_team:
            st.caption("Double-click a team on either table to see its narratives.")
        else:

            # Fixed display order, so a team's cards are always in the same
            # place no matter which team is selected. A narrative is simply
            # left out when its data is missing.
            # Cards render in the order these blocks appear: offense, defense,
            # shooting variance, 3PT shooting, effort, hot starts, comebacks.
            # A card is simply left out when its data is missing.
            narratives = []

            if isinstance(profiles, dict):
                pf_info = (profiles.get("teams", {}) or {}).get(selected_team) or {}
                off_info = pf_info.get("offense")
                def_info = pf_info.get("defense")

                if off_info and off_info.get("ranks"):
                    narratives.append(
                        lambda: render_offensive_overview_narrative(
                            selected_team, off_info
                        )
                    )
                if def_info and def_info.get("ranks"):
                    narratives.append(
                        lambda: render_defensive_formations_narrative(
                            selected_team, def_info
                        )
                    )

            if isinstance(shooting, dict):
                sv_teams = shooting.get("teams", {}) or {}
                sv_avg   = shooting.get("league_average", 0)
                sv_as_of = shooting.get("as_of")
                sv_info  = sv_teams.get(selected_team)

                if sv_info:
                    narratives.append(
                        lambda: render_shooting_variance_narrative(
                            selected_team, sv_info, sv_avg, sv_as_of
                        )
                    )

            if isinstance(threes, dict):
                tp_teams  = threes.get("teams", {}) or {}
                tp_league = threes.get("league") or {}
                tp_prior  = threes.get("prior_season")
                tp_as_of  = threes.get("as_of")
                tp_info   = tp_teams.get(selected_team)

                if tp_info:
                    narratives.append(
                        lambda: render_three_point_shooting_narrative(
                            selected_team, tp_info, tp_league, tp_prior, tp_as_of
                        )
                    )

            if isinstance(effort, dict):
                ef_teams = effort.get("teams", {}) or {}
                ef_avg   = effort.get("league_average", 0)
                ef_info  = ef_teams.get(selected_team)

                if ef_info and ef_info.get("effort_retention") is not None:
                    ef_scored = effort.get("scored_components")
                    narratives.append(
                        lambda: render_effort_narrative(
                            selected_team, ef_info, ef_avg, ef_scored
                        )
                    )

            if isinstance(hot_starts, dict):
                hs_teams = hot_starts.get("teams", {}) or {}
                hs_avg   = hot_starts.get("league_average", 0)
                hs_info  = hs_teams.get(selected_team)

                if hs_info and hs_info.get("q1_lead_pct") is not None:
                    narratives.append(
                        lambda: render_hot_starts_narrative(
                            selected_team, hs_info, hs_avg
                        )
                    )

            if isinstance(comebacks, dict):
                cb_teams = comebacks.get("teams", {}) or {}
                cb_avg   = comebacks.get("league_average", 0)
                cb_info  = cb_teams.get(selected_team) or {}
                cb_count = cb_info.get("count", 0)
                narratives.append(
                    lambda: render_comeback_narrative(
                        selected_team, cb_count, cb_avg, cb_info.get("games", [])
                    )
                )

            if not narratives:
                st.info("Narrative data isn't available for this season yet.")
            for render in narratives:
                with st.container(border=True):
                    render()
    else:
        st.caption("Comparison Chart")
        if not selected_team:
            st.caption("Double-click a team on either table to compare.")
        else:
            show_table(build_comparison(basic_df, selected_team, BASIC_LOWER_IS_BETTER),
                       cell_style=PERCENTILE_STYLE, height=175)

            st.caption("Advanced Stats")
            show_table(build_comparison(adv_df, selected_team, ADV_LOWER_IS_BETTER),
                       cell_style=PERCENTILE_STYLE, height=175)

# Net rating trend (full width, below all tables)
st.divider()
if selected_team and selected_team in weekly.get("teams", {}):
    st.subheader(f"{selected_team} — Net Rating Over Time")
    st.caption("Cumulative season-to-date net rating by week, vs. the league average.")

    chart_df = pd.DataFrame({
        "Week": range(1, len(weekly["weeks"]) + 1),
        selected_team: weekly["teams"][selected_team],
        "League Average": weekly["league_avg"],
    })
    long_df = chart_df.melt("Week", var_name="Series", value_name="Net Rating")

    # Pad the y-axis so the league-average line is never flush against an edge
    vals = [v for v in weekly["teams"][selected_team] if v is not None]
    vals += [v for v in weekly["league_avg"] if v is not None]
    lo, hi = min(vals + [0]), max(vals + [0])
    pad = max(1.0, (hi - lo) * 0.12)
    y_domain = [lo - pad, hi + pad]

    x_axis = alt.X("Week:Q", title=None,
                   axis=alt.Axis(labelExpr="'Week ' + datum.value", tickMinStep=1))
    y_axis = alt.Y("Net Rating:Q", title="Net Rating",
                   scale=alt.Scale(domain=y_domain, nice=False))

    lines = (
        alt.Chart(long_df)
        .mark_line(clip=True)
        .encode(
            x=x_axis,
            y=y_axis,
            color=alt.Color(
                "Series:N", title=None,
                scale=alt.Scale(
                    domain=[selected_team, "League Average"],
                    range=["#1f77b4", "#e74c3c"],  # team blue, league red
                ),
            ),
        )
    )

    # Linear line of best fit for the selected team only (light blue, dashed)
    team_df = (
        chart_df[["Week", selected_team]]
        .dropna()
        .rename(columns={selected_team: "Net Rating"})
    )
    trend = (
        alt.Chart(team_df)
        .transform_regression("Week", "Net Rating")
        .mark_line(strokeDash=[6, 4], color="#5dade2", clip=True)  # light blue
        .encode(x=x_axis, y=y_axis)
    )

    chart = (
        (lines + trend)
        .properties(width="container", height=400, padding={"bottom": 30})
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(chart, use_container_width=True)
else:
    st.caption("Double-click a team above to see its net rating trend over the season.")


# Efficiency landscape (full width, below the net rating trend)
st.divider()
st.subheader("The Efficiency Landscape")
st.caption(
    "Every team's offense against its defense. Up and to the right is good on "
    "both counts; the dashed lines are the league average. Credit @Kirk Goldsberry"
)
render_efficiency_landscape(adv_df, selected_team)

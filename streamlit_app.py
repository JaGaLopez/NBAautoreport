import streamlit as st
import requests
import pandas as pd
import altair as alt
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
from st_aggrid.shared import JsCode

API_URL = "https://nbastats.jglws.com"

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


def show_table(df, *, double_click=False, cell_style=None, height=None):
    gb = GridOptionsBuilder.from_dataframe(df)
    # suppressColumnVirtualisation so every column (even off-screen ones on wide
    # tables) gets measured and autosized to its content.
    gb.configure_grid_options(suppressMovableColumns=True, suppressColumnVirtualisation=True)

    if cell_style is not None:
        gb.configure_default_column(resizable=True, sortable=False, cellStyle=cell_style)
    else:
        gb.configure_default_column(resizable=True, sortable=True)

    if double_click:
        gb.configure_selection(selection_mode="single", use_checkbox=False)
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

    # fitCellContents = size every column to its content (header + longest cell).
    go["autoSizeStrategy"] = {"type": "fitCellContents"}

    kwargs = dict(
        gridOptions=go,
        allow_unsafe_jscode=True,
        update_mode=GridUpdateMode.SELECTION_CHANGED if double_click else GridUpdateMode.NO_UPDATE,
    )
    if height is not None:
        kwargs["height"] = height

    return AgGrid(df, **kwargs)


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
    st.metric(
        "Total Comebacks",
        f"{team_count} vs. {round(league_avg, 1)} (League Average)",
        delta=round(team_count - league_avg, 1),
    )

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
        show_table(games_df, height=175)

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


def render_effort_narrative(team_name, info, league_avg):
    """Render the effort-while-losing narrative: how much of its hustle a team
    keeps in losses relative to its own wins, vs. the league average."""
    score = info["effort_retention"]


    st.metric(
        "Effort While Losing",
        f"{score:.0%} vs. {league_avg:.0%} (League Average)",
        delta=f"{(score - league_avg) * 100:+.0f} pts",
    )

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
        show_table(comp_df, height=175)

    tech_note(
        "100% means they compete equally hard whether winning or losing, "
        "below 100% means the effort drops off once games go bad."
    )


def render_hot_starts_narrative(team_name, info, league_avg):
    """Render the hot-starts narrative: how often a team leads after one
    quarter, and whether that early lead actually survives to halftime."""
    q1_pct = info["q1_lead_pct"]

    st.metric(
        "Hot Starts",
        f"{q1_pct:.0%} vs. {league_avg:.0%} (League Average)",
        delta=f"{(q1_pct - league_avg) * 100:+.0f} pts",
    )

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

    starts_df = pd.DataFrame(
        [
            {"Split": f"Led by {MIN_LEAD}+ after Q1", "Games": info["q1_leads"],
             "Rate": round(q1_pct * 100)},
            {"Split": f"Led by {MIN_LEAD}+ at halftime", "Games": info["h1_leads"],
             "Rate": round(info["h1_lead_pct"] * 100)},
            {"Split": "Held the Q1 lead", "Games": info.get("held"),
             "Rate": round(held_pct * 100) if held_pct is not None else None},
        ]
    )
    show_table(starts_df, height=140)

    tech_note(
        f"A start counts only at {MIN_LEAD} points or more, since a one-point "
        "edge after twelve minutes is noise. Held means the halftime lead was "
        "at least as big as the first-quarter one, so a start that gets "
        "whittled away doesn't count."
    )


def _fgm_band(mean, spread):
    """A one-standard-deviation band of made shots, as a "38-45" string."""
    if mean is None or spread is None:
        return None
    return f"{round(mean - spread)}-{round(mean + spread)}"


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

    # Streaky vs. steady is judged on eFG% swing, not on the width of the band:
    # makes per game also move with pace and attempts, while eFG% isolates how
    # much the shooting itself wobbles. Streaky points down, since a team you
    # can't count on from night to night is the worse thing to be.
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

    # What the season says to expect, before looking at the recent form below.
    if base.get("efg_pct") is not None:
        expected = (
            f"Expected: {base['efg_pct']:.1%} eFG% on {base['fga']:.0f} attempts "
            f"per game, {base['efg_percentile']}th percentile in the league."
        )
        if base.get("open_share") is not None:
            expected += (
                f" {base['open_share']:.0%} of those looks are open or wide open "
                f"({base['open_share_percentile']}th percentile), and they shoot "
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
                "FGM vs. Avg": w.get("fgm_delta"),
                "Swings": w.get("swings"),
                "Form": "Hot" if delta >= 0 else "Cold",
            })
        show_table(pd.DataFrame(rows), height=140)

    # Run lengths, and what usually follows a game on the current side. For most
    # teams this lands near a coin flip, which is the honest answer.
    if streaks.get("repeat_pct") is not None:
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

basic_df, adv_df, weekly, comebacks, effort, hot_starts, shooting = data

# Layout
# One column pair, with each side stacking its own content. Two separate
# st.columns() rows would align the second row across both sides, leaving a gap
# under the basic table whenever the narratives column is taller.
left, right = st.columns(2)

# Render the two selectable source tables first (both double-clickable)
with left:
    st.caption("Per Game Stats")
    basic_result = show_table(basic_df, double_click=True)

    st.caption("Advanced Stats")
    adv_result = show_table(adv_df, double_click=True)

# Figure out which table the user most recently clicked
basic_sel = selected_team_from(basic_result)
adv_sel   = selected_team_from(adv_result)

selected_team = st.session_state.get("selected_team")
if basic_sel is not None and basic_sel != st.session_state.get("prev_basic_sel"):
    selected_team = basic_sel
elif adv_sel is not None and adv_sel != st.session_state.get("prev_adv_sel"):
    selected_team = adv_sel
elif selected_team is None:
    selected_team = basic_sel or adv_sel

st.session_state["prev_basic_sel"] = basic_sel
st.session_state["prev_adv_sel"]   = adv_sel
st.session_state["selected_team"]  = selected_team

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
            narratives = []

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

            if isinstance(effort, dict):
                ef_teams = effort.get("teams", {}) or {}
                ef_avg   = effort.get("league_average", 0)
                ef_info  = ef_teams.get(selected_team)

                if ef_info and ef_info.get("effort_retention") is not None:
                    narratives.append(
                        lambda: render_effort_narrative(
                            selected_team, ef_info, ef_avg
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

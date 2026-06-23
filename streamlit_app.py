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


def show_table(df, *, double_click=False, cell_style=None, height=None, col_widths=None):
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_grid_options(suppressMovableColumns=True)

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

    # Lock each column to a deterministic width sized to its header + cell content.
    # Wide tables scroll horizontally; nothing clips, nothing over-expands.
    for col in go.get("columnDefs", []):
        col.update(no_filter)
        field = col.get("field")
        if field in df.columns:
            if col_widths and field in col_widths:
                w = col_widths[field]  # caller-specified fixed width
            else:
                longest = max([len(str(field))] + [len(str(v)) for v in df[field].tolist()])
                if pd.api.types.is_numeric_dtype(df[field]):
                    w = max(60, longest * 9 + 26)
                else:  # text columns (Team / Metric) use a tighter proportional width
                    w = max(60, longest * 6 + 4)
            col["width"] = w
            col["minWidth"] = w
            col["maxWidth"] = w

    kwargs = dict(
        gridOptions=go,
        allow_unsafe_jscode=True,
        use_container_width=True,
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

    basic_raw["2P"]  = basic_raw["FGM"] - basic_raw["FG3M"]
    basic_raw["2PA"] = basic_raw["FGA"] - basic_raw["FG3A"]
    basic_raw["2P%"] = basic_raw["2P"] / basic_raw["2PA"]

    basic_df = basic_raw[[c for c in BASIC_COLS if c in basic_raw.columns]].rename(columns=BASIC_COLS)
    adv_df   = adv_raw[[c for c in ADV_COLS if c in adv_raw.columns]].rename(columns=ADV_COLS)

    return round_for_display(basic_df), round_for_display(adv_df), weekly, comebacks


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


def render_comeback_narrative(team_name, team_count, league_avg, games):
    """Render the 4th-quarter-comebacks narrative: the team's total vs. the league
    average (the metric's arrow shows the gap), with a historic-low note and the
    team's comeback games."""
    st.metric(
        "Total Comebacks vs. League Avg",
        team_count,
        delta=round(team_count - league_avg, 1),
    )

    # Note a season that is (or ties) this team's fewest comebacks across the
    # seasons we have — only meaningful when there's more than one season and the
    # counts actually vary.
    history = team_comeback_counts(team_name)
    if len(history) > 1:
        lo, hi = min(history.values()), max(history.values())
        if team_count == lo < hi:
            st.caption(
                f"📉 Historic low — fewest comebacks for {team_name} "
                f"in our {len(history)} seasons of data."
            )

    if not games:
        return

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
    show_table(
        games_df,
        height=175,
        col_widths={
            "Date": 70,
            "Opponent": 220,   # lots of room so the opponent is clearly visible
            "Q3 Deficit": 100,
            "Final": 80,
            "Final (Opp)": 80,  # matched to Final
        },
    )


# ── Page setup ──────────────────────────────────────────────────────────────
st.set_page_config(layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] > div:nth-child(2) {
        border-left: 2px solid #cccccc;
        padding-left: 2rem;
    }
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
    view = st.selectbox("View", ["Stats", "Narratives"])

with st.spinner("Loading stats..."):
    data = load_data(season)

if data is None:
    st.warning(f"Stats for {season} haven't been precomputed yet. Try another season.")
    st.stop()

basic_df, adv_df, weekly, comebacks = data

# ── Layout ──────────────────────────────────────────────────────────────────
# Create both column rows up front so we can fill them in any order.
row1_left, row1_right = st.columns(2)
row2_left, row2_right = st.columns(2)

# Render the two selectable source tables first (both double-clickable)
with row1_left:
    st.caption("Per Game Stats")
    basic_result = show_table(basic_df, double_click=True)

with row2_left:
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
with row1_right:
    if view == "Narratives":
        st.caption("Narratives")
        if not selected_team:
            st.caption("Double-click a team on either table to see its narratives.")
        elif comebacks is None:
            st.info("Comeback data isn't available for this season yet.")
        else:
            cb_teams = comebacks.get("teams", {}) if isinstance(comebacks, dict) else {}
            cb_avg   = comebacks.get("league_average", 0) if isinstance(comebacks, dict) else 0
            cb_info  = cb_teams.get(selected_team) or {}
            cb_count = cb_info.get("count", 0)

            # Each narrative stat is rendered in its own encapsulated container,
            # ordered top-to-bottom by how far the team sits from the league avg.
            narratives = [{
                "distinctness": abs(cb_count - cb_avg),
                "render": lambda: render_comeback_narrative(
                    selected_team, cb_count, cb_avg, cb_info.get("games", [])
                ),
            }]
            for n in sorted(narratives, key=lambda x: x["distinctness"], reverse=True):
                with st.container(border=True):
                    n["render"]()
    else:
        st.caption("Comparison Chart")
        if not selected_team:
            st.caption("Double-click a team on either table to compare.")
        else:
            show_table(build_comparison(basic_df, selected_team, BASIC_LOWER_IS_BETTER),
                       cell_style=PERCENTILE_STYLE, height=175)

with row2_right:
    if view == "Stats" and selected_team:
        st.caption("Advanced Stats")
        show_table(build_comparison(adv_df, selected_team, ADV_LOWER_IS_BETTER),
                   cell_style=PERCENTILE_STYLE, height=175)

# ── Net rating trend (full width, below all tables) ──────────────────────────
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

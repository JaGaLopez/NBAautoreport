import streamlit as st
import requests
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
from st_aggrid.shared import JsCode

API_URL = "https://nbaautoreport.jglws.com"

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


def show_table(df, *, double_click=False, cell_style=None, height=None):
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

    # Size every column to fit its content + header; wide tables scroll instead of clipping
    go["autoSizeStrategy"] = {"type": "fitCellContents"}

    no_filter = {
        "filter": False,
        "suppressMenu": True,
        "suppressHeaderFilterButton": True,
        "suppressHeaderMenuButton": True,
    }
    go.setdefault("defaultColDef", {}).update(no_filter)
    for col in go.get("columnDefs", []):
        col.update(no_filter)

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
    basic_raw = pd.DataFrame(requests.get(f"{API_URL}/teams/{season}").json())
    adv_raw   = pd.DataFrame(requests.get(f"{API_URL}/teams/{season}/advanced").json())

    basic_raw["2P"]  = basic_raw["FGM"] - basic_raw["FG3M"]
    basic_raw["2PA"] = basic_raw["FGA"] - basic_raw["FG3A"]
    basic_raw["2P%"] = basic_raw["2P"] / basic_raw["2PA"]

    basic_df = basic_raw[[c for c in BASIC_COLS if c in basic_raw.columns]].rename(columns=BASIC_COLS)
    adv_df   = adv_raw[[c for c in ADV_COLS if c in adv_raw.columns]].rename(columns=ADV_COLS)

    return round_for_display(basic_df), round_for_display(adv_df)


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

st.title("NBA Team Stats")

sel_col1, sel_col2 = st.columns(2)
with sel_col1:
    season = st.selectbox("Season", ["2024-25", "2023-24", "2022-23", "2021-22"])
with sel_col2:
    view = st.selectbox("View", ["Stats", "Narratives"])

with st.spinner("Loading stats..."):
    basic_df, adv_df = load_data(season)

# ── Layout ──────────────────────────────────────────────────────────────────
# Row 1: basic tables side by side
row1_left, row1_right = st.columns(2)

with row1_left:
    st.subheader("All Teams")
    result = show_table(basic_df, double_click=True)

    selected_rows = result["selected_rows"]
    selected_team = None
    if selected_rows is not None:
        if hasattr(selected_rows, "iloc") and len(selected_rows) > 0:
            selected_team = selected_rows.iloc[0]["Team"]
        elif isinstance(selected_rows, list) and len(selected_rows) > 0:
            selected_team = selected_rows[0]["Team"]

with row1_right:
    st.subheader("Food for Thought")

    if view == "Narratives":
        st.info("Narratives coming soon.")
    elif not selected_team:
        st.caption("Double-click a team on the left to compare.")
    else:
        show_table(build_comparison(basic_df, selected_team, BASIC_LOWER_IS_BETTER),
                   cell_style=PERCENTILE_STYLE, height=175)

# Row 2: advanced tables side by side (aligned because they start their own column row)
row2_left, row2_right = st.columns(2)

with row2_left:
    st.caption("Advanced Stats")
    show_table(adv_df)

with row2_right:
    if view == "Stats" and selected_team:
        st.caption("Advanced Stats")
        show_table(build_comparison(adv_df, selected_team, ADV_LOWER_IS_BETTER),
                   cell_style=PERCENTILE_STYLE, height=175)

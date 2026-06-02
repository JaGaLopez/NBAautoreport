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
ADV_LOWER_IS_BETTER = {"DRTG", "TOV%"}

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
    basic_raw = pd.DataFrame(requests.get(f"{API_URL}/teams/{season}").json())
    adv_raw = pd.DataFrame(requests.get(f"{API_URL}/teams/{season}/advanced").json())

    basic_raw["2P"] = basic_raw["FGM"] - basic_raw["FG3M"]
    basic_raw["2PA"] = basic_raw["FGA"] - basic_raw["FG3A"]
    basic_raw["2P%"] = (basic_raw["2P"] / basic_raw["2PA"]).round(3)

    basic_df = basic_raw[[c for c in BASIC_COLS if c in basic_raw.columns]].rename(columns=BASIC_COLS)
    adv_df = adv_raw[[c for c in ADV_COLS if c in adv_raw.columns]].rename(columns=ADV_COLS)


def build_comparison(df, team_name, lower_is_better_set):
    stat_cols = [c for c in df.columns if c != "Team"]
    team_row = df[df["Team"] == team_name][stat_cols].iloc[0]
    league_avg = df[stat_cols].mean().round(2)
    delta = (team_row - league_avg).round(2)

    percentile_row = {}
    for col in stat_cols:
        val = team_row[col]
        all_vals = df[col].dropna()
        pct = round((all_vals < val).sum() / len(all_vals) * 100, 1)
        if col in lower_is_better_set:
            pct = round(100 - pct, 1)
        percentile_row[col] = pct

    return pd.DataFrame(
        [team_row, league_avg, delta, pd.Series(percentile_row)],
        index=[team_name, "League Average", "Delta", "Percentile"]
    )


def style_comparison(comp_df):
    def color_percentile(val):
        try:
            v = float(val)
            if v >= 80:   return "background-color: #27ae60; color: white"
            elif v >= 60: return "background-color: #a8e6cf"
            elif v >= 40: return "background-color: #f0f0f0"
            elif v >= 20: return "background-color: #ffb3b3"
            else:         return "background-color: #e74c3c; color: white"
        except:
            return ""

    return comp_df.style.apply(
        lambda row: [color_percentile(v) if row.name == "Percentile" else "" for v in row],
        axis=1
    )


col_left, col_right = st.columns(2)

with col_left:
    st.subheader("All Teams")

    gb = GridOptionsBuilder.from_dataframe(basic_df)
    gb.configure_selection(selection_mode="single", use_checkbox=False)
    gb.configure_grid_options(
        suppressRowClickSelection=True,
        onRowDoubleClicked=JsCode("function(e){ e.node.setSelected(true); }")
    )
    result = AgGrid(
        basic_df,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        use_container_width=True,
    )

    st.caption("Advanced Stats")
    st.dataframe(adv_df, use_container_width=True, hide_index=True)

    selected_rows = result["selected_rows"]
    selected_team = (
        selected_rows.iloc[0]["Team"]
        if selected_rows is not None and len(selected_rows) > 0
        else None
    )

with col_right:
    st.subheader("Food for Thought")

    if view == "Narratives":
        st.info("Narratives coming soon.")
    elif not selected_team:
        st.caption("Double-click a team on the left to compare.")
    else:
        st.dataframe(style_comparison(build_comparison(basic_df, selected_team, BASIC_LOWER_IS_BETTER)), use_container_width=True)

        st.caption("Advanced Stats")
        st.dataframe(style_comparison(build_comparison(adv_df, selected_team, ADV_LOWER_IS_BETTER)), use_container_width=True)

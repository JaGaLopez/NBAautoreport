import streamlit as st
import requests
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
from st_aggrid.shared import JsCode

API_URL = "https://nbaautoreport.jglws.com"

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
    response = requests.get(f"{API_URL}/teams/{season}")
    data = response.json()
    df = pd.DataFrame(data)
    df = df.drop(columns=["TEAM_ID", "GP", "MIN"], errors="ignore")

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("All Teams")

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_selection(selection_mode="single", use_checkbox=False)
    gb.configure_grid_options(
        suppressRowClickSelection=True,
        onRowDoubleClicked=JsCode("function(e){ e.node.setSelected(true); }")
    )
    grid_opts = gb.build()

    result = AgGrid(
        df,
        gridOptions=grid_opts,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        use_container_width=True,
    )

    selected_rows = result["selected_rows"]
    selected_team = (
        selected_rows.iloc[0]["TEAM_NAME"]
        if selected_rows is not None and len(selected_rows) > 0
        else None
    )

with col_right:
    st.subheader("Food for Thought")

    if view == "Narratives":
        st.info("Narratives coming soon.")
    else:
        if not selected_team:
            st.caption("Double-click a team on the left to compare.")
        else:
            lower_is_better = {"TOV", "PF", "BLKA"}

            rank_cols = {col for col in df.columns if col.endswith("_RANK")}
            stat_cols = [
                col for col in df.columns
                if col != "TEAM_NAME"
                and col not in rank_cols
                and pd.api.types.is_numeric_dtype(df[col])
            ]

            team_row = df[df["TEAM_NAME"] == selected_team][stat_cols].iloc[0]
            league_avg = df[stat_cols].mean().round(2)
            delta = (team_row - league_avg).round(2)

            percentile_row = {}
            for col in stat_cols:
                val = team_row[col]
                all_vals = df[col].dropna()
                pct = round((all_vals < val).sum() / len(all_vals) * 100, 1)
                if col in lower_is_better:
                    pct = round(100 - pct, 1)
                percentile_row[col] = pct

            comparison = pd.DataFrame(
                [team_row, league_avg, delta, pd.Series(percentile_row)],
                index=[selected_team, "League Average", "Delta", "Percentile"]
            )

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

            styled = comparison.style.apply(
                lambda row: [color_percentile(v) if row.name == "Percentile" else "" for v in row],
                axis=1
            )

            st.dataframe(styled, use_container_width=True)

import streamlit as st
import requests
import pandas as pd

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
season = st.selectbox("Season", ["2024-25", "2023-24", "2022-23", "2021-22"])

with st.spinner("Loading stats..."):
    response = requests.get(f"{API_URL}/teams/{season}")
    data = response.json()
    df = pd.DataFrame(data)
    df = df.drop(columns=["TEAM_ID", "GP", "MIN"], errors="ignore")

col_left, col_right = st.columns(2)

with col_left:
    st.markdown("**All Teams**")
    event = st.dataframe(df, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")

selected_team = None
if event.selection.rows:
    selected_team = df.iloc[event.selection.rows[0]]["TEAM_NAME"]

with col_right:
    st.markdown("**Food for Thought**")
    if selected_team:
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
        vs_league = (delta / df[stat_cols].std()).round(2)

        comparison = pd.DataFrame(
            [team_row, league_avg, delta, vs_league],
            index=[selected_team, "League Average", "Delta", "vs League (σ)"]
        )

        st.dataframe(comparison, use_container_width=True)
    else:
        st.caption("Click a team on the left to compare.")

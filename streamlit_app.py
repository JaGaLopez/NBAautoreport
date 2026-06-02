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

col_left, col_right = st.columns(2)

with col_left:
    st.title("NBA Team Stats")

    season = st.selectbox("Season", ["2024-25", "2023-24", "2022-23", "2021-22"])

    with st.spinner("Loading stats..."):
        response = requests.get(f"{API_URL}/teams/{season}")
        data = response.json()
        df = pd.DataFrame(data)
        df = df.drop(columns=["TEAM_ID"], errors="ignore")

    st.dataframe(df, use_container_width=True, hide_index=True)

with col_right:
    st.title("Food for Thought: Pick a Team")



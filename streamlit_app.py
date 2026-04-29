import streamlit as st
import requests
import pandas as pd

API_URL = "https://nbaautoreport.jglws.com"

st.title("NBA Team Stats")

season = st.selectbox("Season", ["2024-25", "2023-24", "2022-23", "2021-22"])

with st.spinner("Loading stats..."):
    response = requests.get(f"{API_URL}/teams/{season}")
    data = response.json()
    df = pd.DataFrame(data)

st.dataframe(df, use_container_width=True)
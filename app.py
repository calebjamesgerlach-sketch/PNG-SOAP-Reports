import os
import json
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px

# 1. Page Configuration
st.set_page_config(page_title="Construction SOAP Dashboard", layout="wide")
st.title("Jobsite Daily SOAP Tracker")


@st.cache_data(ttl=60)
def load_data():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Priority 1: Local credentials.json
    if os.path.exists("credentials.json"):
        credentials = Credentials.from_service_account_file("credentials.json", scopes=scope)
        gc = gspread.authorize(credentials)
    # Priority 2: Streamlit Cloud Secrets (Raw JSON)
    elif "gcp_raw_json" in st.secrets:
        creds_dict = json.loads(st.secrets["gcp_raw_json"])
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
        gc = gspread.authorize(credentials)
    # Priority 3: Streamlit Cloud Secrets (TOML)
    elif "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
        gc = gspread.authorize(credentials)
    else:
        raise FileNotFoundError("No valid credentials found in local directory or Streamlit secrets.")
        
    sheet = gc.open("SOAP_Daily_Logs").sheet1
    records = sheet.get_all_records()
    df = pd.DataFrame(records)

    df["Parsed Date"] = pd.to_datetime(df["Current Date"], errors="coerce")
    return df


# Fetch data
with st.spinner("Connecting to Google Sheets..."):
    try:
        df = load_data()
        st.success(f"Data synchronized successfully. Total logs: {len(df)}")
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        st.stop()


# --- Shared Helpers & Calculations ---
def count_tools(series):
    all_tools = []
    for item in series.dropna():
        tools = [t.strip() for t in str(item).split(",") if t.strip() and t.strip().lower() not in ["none", "nan", ""]]
        all_tools.extend(tools)
    return len(all_tools)


def extract_tools_df(dataset):
    tool_records = []
    for _, row in dataset.iterrows():
        proj = row.get("Project Name", "Unknown")
        raw_tools = str(row.get("Equipment Used", ""))
        if raw_tools and raw_tools.lower() not in ["nan", "none", ""]:
            for tool in raw_tools.split(","):
                tool_clean = tool.strip()
                if tool_clean and tool_clean.lower() != "none":
                    tool_records.append({"Project Name": proj, "Tool": tool_clean})
    return pd.DataFrame(tool_records) if tool_records else pd.DataFrame(columns=["Project Name", "Tool"])


# Top Dashboard Selector Toggle
dashboard_view = st.radio(
    "Select Dashboard View",
    ["📊 Analytics", "👷 Crew", "🛠️ Equipment"],
    horizontal=True,
    label_visibility="collapsed"
)

st.markdown("---")

# =========================================================
# DASHBOARD 1: ANALYTICS (Master Roll-up & CQI Dashboard)
# =========================================================
if dashboard_view == "📊 Analytics":
    # Macro KPIs
    col1, col2, col3 = st.columns(3)
    cutoff_date = pd.Timestamp.now() - pd.Timedelta(days=7)
    mask_7d = df["Parsed Date"] >= cutoff_date

    total_logs = len(df)
    logs_7d = int(mask_7d.sum())

    numeric_hours = pd.to_numeric(df.get("Man Hours", 0), errors="coerce").fillna(0)
    total_hours = numeric_hours.sum()
    hours_7d = numeric_hours[mask_7d].sum()

    equip_series = df.get("Equipment Used", pd.Series())
    total_tools_count = count_tools(equip_series)
    tools_7d_count = count_tools(equip_series[mask_7d])

    col1.metric("Total Reports Logged", total_logs, delta=f"{logs_7d} in last 7 days", delta_color="off")
    col2.metric("Total Man-Hours Logged", f"{total_hours:,.1f} hrs", delta=f"{hours_7d:,.1f} hrs in last 7 days", delta_color="off")
    col3.metric("Total Equipment Deployed", total_tools_count, delta=f"{tools_7d_count} in last 7 days", delta_color="off")

    st.markdown("---")

    # Sidebar Filter: Project Umbrella
    st.sidebar.header("Navigation & Filters")
    project_list = ["All"] + sorted([p for p in df["Project Name"].dropna().unique() if str(p).strip()])
    selected_project = st.sidebar.selectbox("Select Project (Umbrella)", project_list)

    if selected_project == "All":
        project_df = df.copy()
    else:
        project_df = df[df["Project Name"] == selected_project].copy()

    # Tabs (Daily SOAP tab removed)
    tab_umbrella_summary, tab_analytics, tab_raw = st.tabs([
        "🏢 Project Master Roll-Up",
        "📊 CQI Analytics",
        "📁 Raw Data Table"
    ])

    with tab_umbrella_summary:
        if selected_project == "All":
            st.subheader("All Projects Overview")
            summary_table = df.groupby("Project Name").agg(
                Total_Reports=("Current Date", "count"),
                Total_Hours=("Man Hours", lambda x: pd.to_numeric(x, errors="coerce").fillna(0).sum()),
                First_Log=("Parsed Date", "min"),
                Last_Log=("Parsed Date", "max")
            ).reset_index()

            summary_table["First_Log"] = summary_table["First_Log"].dt.strftime("%Y-%m-%d")
            summary_table["Last_Log"] = summary_table["Last_Log"].dt.strftime("%Y-%m-%d")

            st.dataframe(
                summary_table.rename(columns={
                    "Project Name": "Project (Umbrella)",
                    "Total_Reports": "Total Daily Reports",
                    "Total_Hours": "Total Man-Hours",
                    "First_Log": "First Activity",
                    "Last_Log": "Latest Activity"
                }),
                use_container_width=True
            )
        else:
            st.subheader(f"Master Summary for Project: {selected_project}")
            p_hours = pd.to_numeric(project_df.get("Man Hours", 0), errors="coerce").fillna(0).sum()
            p_tools = count_tools(project_df.get("Equipment Used", pd.Series()))
            p_entries = len(project_df)

            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Total Daily Reports on File", p_entries)
            mc2.metric("Cumulative Project Man-Hours", f"{p_hours:,.1f} hrs")
            mc3.metric("Total Equipment Deployments", p_tools)

            st.markdown("---")
            st.markdown("### Cumulative Safety & QC Log (All Reports)")
            assess_df = project_df.dropna(subset=["Assessment"]).sort_values(by="Parsed Date", ascending=False)
            for _, a_row in assess_df.iterrows():
                if str(a_row["Assessment"]).strip() and str(a_row["Assessment"]).lower() != "no entries logged.":
                    st.warning(f"**{a_row.get('Current Date')} (by {a_row.get('Name and Title', 'Crew')}):**\n{a_row.get('Assessment')}")

    with tab_analytics:
        st.subheader("Continuous Quality Improvement (CQI) Metrics")
        if not project_df.empty:
            c1, c2 = st.columns(2)

            if selected_project != "All":
                fig_hours = px.bar(
                    project_df.sort_values("Parsed Date"),
                    x="Current Date",
                    y=pd.to_numeric(project_df.get("Man Hours", 0), errors="coerce"),
                    title=f"Man-Hours Over Time — {selected_project}",
                    labels={"Man Hours": "Hours", "Current Date": "Report Date"}
                )
            else:
                fig_hours = px.bar(
                    project_df,
                    x="Project Name",
                    y=pd.to_numeric(project_df.get("Man Hours", 0), errors="coerce"),
                    title="Total Man-Hours by Project",
                    labels={"y": "Hours", "Project Name": "Project"}
                )
            c1.plotly_chart(fig_hours, use_container_width=True)

            df_tools = extract_tools_df(project_df)
            if not df_tools.empty:
                tools_summary = df_tools.groupby("Tool").size().reset_index(name="Count").sort_values(by="Count", ascending=False)
                fig_proj_tools = px.bar(
                    tools_summary.head(10),
                    x="Count",
                    y="Tool",
                    orientation="h",
                    title="Top Equipment Used",
                    text="Count"
                )
                fig_proj_tools.update_traces(textposition="outside")
                c2.plotly_chart(fig_proj_tools, use_container_width=True)
            else:
                c2.info("No equipment deployments recorded.")

            st.markdown("---")
            weather_col = next((col for col in project_df.columns if "weather" in col.lower()), None)
            if weather_col:
                weather_series = project_df[weather_col].astype(str).str.strip()
                weather_cleaned = weather_series[~weather_series.str.lower().isin(["", "nan", "none", "n/a"])]

                if not weather_cleaned.empty:
                    weather_palette = {
                        "Clear / Sunny": "#FFC107", "Sunny": "#FFC107",
                        "Partly Cloudy": "#90CAF9", "Overcast": "#78909C", "Cloudy": "#78909C",
                        "Light Rain": "#42A5F5", "Rain": "#1E88E5", "Heavy Rain / Storm": "#1565C0",
                        "Snow": "#E0F7FA", "Windy": "#B0BEC5", "Extreme Heat": "#FF5722", "Extreme Cold": "#00BCD4"
                    }
                    fig_weather = px.pie(
                        names=weather_cleaned,
                        title=f"Weather Distribution ({weather_col})",
                        hole=0.4,
                        color=weather_cleaned,
                        color_discrete_map=weather_palette
                    )
                    fig_weather.update_traces(textposition="inside", textinfo="percent+label")
                    st.plotly_chart(fig_weather, use_container_width=True)

    with tab_raw:
        st.subheader("Raw Submission Table")
        st.dataframe(project_df, use_container_width=True)


# =========================================================
# DASHBOARD 2: CREW (Personnel & Submitter Hours)
# =========================================================
elif dashboard_view == "👷 Crew":
    crew_df = df.copy()
    crew_df["Numeric_Hours"] = pd.to_numeric(crew_df.get("Man Hours", 0), errors="coerce").fillna(0)
    crew_df["Submitter"] = crew_df.get("Name and Title", "Unknown").astype(str).str.strip()

    total_crew_hours = crew_df["Numeric_Hours"].sum()
    unique_crew_members = crew_df["Submitter"].nunique()
    avg_hours_per_log = crew_df["Numeric_Hours"].mean() if len(crew_df) > 0 else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Man-Hours Logged", f"{total_crew_hours:,.1f} hrs")
    c2.metric("Active Field Submitter(s)", unique_crew_members)
    c3.metric("Average Hours / Log", f"{avg_hours_per_log:.1f} hrs")

    st.markdown("---")
    st.subheader("Man-Hours Breakdown by Submitter")

    # Aggregate by Submitter
    crew_summary = crew_df.groupby("Submitter").agg(
        Total_Hours=("Numeric_Hours", "sum"),
        Total_Reports=("Current Date", "count"),
        Projects_Covered=("Project Name", lambda x: ", ".join(sorted(set(str(p) for p in x.dropna()))))
    ).reset_index().sort_values(by="Total_Hours", ascending=False)

    col_chart, col_table = st.columns([1, 1])

    with col_chart:
        fig_crew = px.bar(
            crew_summary,
            x="Submitter",
            y="Total_Hours",
            title="Total Hours Logged per Submitter",
            text="Total_Hours",
            labels={"Total_Hours": "Hours", "Submitter": "Crew Member"}
        )
        fig_crew.update_traces(texttemplate="%{text:.1f}h", textposition="outside")
        st.plotly_chart(fig_crew, use_container_width=True)

    with col_table:
        st.write("#### Submitter Summary Table")
        st.dataframe(
            crew_summary.rename(columns={
                "Submitter": "Crew Lead / Submitter",
                "Total_Hours": "Total Man-Hours",
                "Total_Reports": "Logs Filed",
                "Projects_Covered": "Projects Worked"
            }),
            use_container_width=True
        )


# =========================================================
# DASHBOARD 3: EQUIPMENT (Tools & Deployment Metrics)
# =========================================================
elif dashboard_view == "🛠️ Equipment":
    df_tools = extract_tools_df(df)

    total_tool_deployments = len(df_tools)
    
    if not df_tools.empty:
        # Most used tool
        tool_counts = df_tools["Tool"].value_counts()
        most_used_tool = tool_counts.index[0]
        most_used_count = tool_counts.iloc[0]

        # Project with most tools deployed
        project_tool_counts = df_tools["Project Name"].value_counts()
        top_project_name = project_tool_counts.index[0]
        top_project_count = project_tool_counts.iloc[0]
    else:
        most_used_tool = "None"
        most_used_count = 0
        top_project_name = "None"
        top_project_count = 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Tools Deployed", total_tool_deployments)
    c2.metric("Most Used Equipment", most_used_tool, delta=f"{most_used_count} uses", delta_color="off")
    c3.metric("Top Equipment Project", top_project_name, delta=f"{top_project_count} deployments", delta_color="off")

    st.markdown("---")
    st.subheader("Equipment Usage & Allocation")

    if not df_tools.empty:
        col_tool_chart, col_proj_chart = st.columns(2)

        with col_tool_chart:
            tool_agg = df_tools.groupby("Tool").size().reset_index(name="Deployments").sort_values(by="Deployments", ascending=True)
            fig_tools = px.bar(
                tool_agg,
                x="Deployments",
                y="Tool",
                orientation="h",
                title="Equipment Frequency",
                text="Deployments"
            )
            fig_tools.update_traces(textposition="outside")
            st.plotly_chart(fig_tools, use_container_width=True)

        with col_proj_chart:
            proj_tool_agg = df_tools.groupby(["Project Name", "Tool"]).size().reset_index(name="Deployments")
            fig_proj_tools = px.bar(
                proj_tool_agg,
                x="Project Name",
                y="Deployments",
                color="Tool",
                title="Equipment Deployed by Project",
                barmode="stack"
            )
            st.plotly_chart(fig_proj_tools, use_container_width=True)
    else:
        st.info("No equipment deployments recorded in any daily logs yet.")

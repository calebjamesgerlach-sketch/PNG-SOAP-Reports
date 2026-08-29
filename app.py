import streamlit as st
import pandas as pd
import gspread
import json
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
    
    # Check if raw JSON string secret is present
    if "gcp_raw_json" in st.secrets:
        creds_dict = json.loads(st.secrets["gcp_raw_json"])
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
        gc = gspread.authorize(credentials)
    elif "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
        gc = gspread.authorize(credentials)
    else:
        gc = gspread.service_account(filename="credentials.json")
        
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

# --- Top-level Macro KPI Metrics ---
col1, col2, col3 = st.columns(3)

cutoff_date = pd.Timestamp.now() - pd.Timedelta(days=7)
mask_7d = df["Parsed Date"] >= cutoff_date

total_logs = len(df)
logs_7d = int(mask_7d.sum())

numeric_hours = pd.to_numeric(df.get("Man Hours", 0), errors="coerce").fillna(0)
total_hours = numeric_hours.sum()
hours_7d = numeric_hours[mask_7d].sum()


def count_tools(series):
    all_tools = []
    for item in series.dropna():
        tools = [t.strip() for t in str(item).split(",") if t.strip() and t.strip().lower() not in ["none", "nan", ""]]
        all_tools.extend(tools)
    return len(all_tools)


equip_series = df.get("Equipment Used", pd.Series())
total_tools_count = count_tools(equip_series)
tools_7d_count = count_tools(equip_series[mask_7d])

col1.metric("Total Reports Logged", total_logs, delta=f"{logs_7d} in last 7 days", delta_color="off")
col2.metric("Total Man-Hours Logged", f"{total_hours:,.1f} hrs", delta=f"{hours_7d:,.1f} hrs in last 7 days",
            delta_color="off")
col3.metric("Total Equipment Deployed", total_tools_count, delta=f"{tools_7d_count} in last 7 days", delta_color="off")

st.markdown("---")

# --- Sidebar: Project (Umbrella) & Date (Report ID) Filters ---
st.sidebar.header("Navigation & Filters")

# Project is the top-level Umbrella
project_list = ["All"] + sorted([p for p in df["Project Name"].dropna().unique() if str(p).strip()])
selected_project = st.sidebar.selectbox("Select Project (Umbrella)", project_list)

# Filter by selected project first (using .copy() to prevent Pandas warnings)
if selected_project == "All":
    project_df = df.copy()
else:
    project_df = df[df["Project Name"] == selected_project].copy()

# Sort most recent first
project_df = project_df.sort_values(by="Parsed Date", ascending=False)

# Build a unique label for every report using existing columns + row index
project_df["Report_Display_Label"] = (
    project_df["Current Date"].astype(str) + 
    " — " + 
    project_df.get("Name and Title", "Field Lead").astype(str) + 
    " (Log #" + project_df.index.astype(str) + ")"
)

# Populate dropdown options
report_options = ["All Entries"] + project_df["Report_Display_Label"].tolist()
selected_report = st.sidebar.selectbox("Filter Specific Daily Log", report_options)

# Apply child log filter
if selected_report != "All Entries":
    filtered_df = project_df[project_df["Report_Display_Label"] == selected_report]
else:
    filtered_df = project_df
# Tab Navigation
tab_soap, tab_umbrella_summary, tab_analytics, tab_raw = st.tabs([
    "📋 Daily SOAP Entries",
    "🏢 Project Master Roll-Up",
    "📊 CQI Analytics",
    "📁 Raw Data Table"
])

# --- TAB 1: Individual Daily SOAP Entries ---
with tab_soap:
    st.subheader("Daily Field Logs")
    if filtered_df.empty:
        st.info("No daily reports found for this selection.")
    else:
        display_df = filtered_df.sort_values(by="Parsed Date", ascending=False)
        for idx, row in display_df.iterrows():
            report_title = f"📅 {row.get('Current Date', 'N/A')} — {row.get('Project Name', 'Unknown')} (Inspector/Lead: {row.get('Name and Title', 'Unknown')})"
            with st.expander(report_title, expanded=(selected_report != "All Entries")):
                c1, c2, c3 = st.columns(3)
                c1.write(f"**Location:** {row.get('Location Address', 'N/A')}")
                c2.write(f"**Travel Time:** {row.get('Travel Time', 'N/A')}")
                c3.write(f"**Man Hours:** {row.get('Man Hours', 'N/A')} hrs")

                st.markdown("#### SOAP Breakdown")
                st.info(
                    f"**S (Subjective - Crew reports, delays, concerns):**\n{row.get('Subjective', 'No entries logged.')}")
                st.write(
                    f"**O (Objective - Work completed, quantities, deliveries):**\n{row.get('Objective', 'No entries logged.')}")
                st.warning(
                    f"**A (Assessment - Quality control, safety issues, compliance):**\n{row.get('Assessment', 'No entries logged.')}")
                st.success(f"**P (Plan - Next day targets, trades needed):**\n{row.get('Plan', 'No entries logged.')}")

# --- TAB 2: Project Master Roll-Up ---
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

        # Cumulative Safety & QC Log
        st.markdown("### Cumulative Safety & QC Log (All Reports)")
        assess_df = project_df.dropna(subset=["Assessment"]).sort_values(by="Parsed Date", ascending=False)
        for _, a_row in assess_df.iterrows():
            if str(a_row["Assessment"]).strip() and str(a_row["Assessment"]).lower() != "no entries logged.":
                st.warning(
                    f"**{a_row.get('Current Date')} (by {a_row.get('Name and Title', 'Crew')}):**\n{a_row.get('Assessment')}")

# --- TAB 3: CQI Analytics ---
with tab_analytics:
    st.subheader("Continuous Quality Improvement (CQI) Metrics")
    if not project_df.empty:
        c1, c2 = st.columns(2)

        # 1. Man-Hours Distribution
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

        # 2. Tool / Equipment Deployment Breakdown
        tool_records = []
        for _, row in project_df.iterrows():
            proj = row.get("Project Name", "Unknown")
            raw_tools = str(row.get("Equipment Used", ""))
            if raw_tools and raw_tools.lower() not in ["nan", "none", ""]:
                for tool in raw_tools.split(","):
                    tool_clean = tool.strip()
                    if tool_clean and tool_clean.lower() != "none":
                        tool_records.append({"Project Name": proj, "Tool": tool_clean})

        if tool_records:
            df_tools = pd.DataFrame(tool_records)
            tools_summary = df_tools.groupby("Tool").size().reset_index(name="Count").sort_values(by="Count",
                                                                                                  ascending=False)
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

        # 3. Weather Distribution Pie Chart
        weather_col = next((col for col in project_df.columns if "weather" in col.lower()), None)
        if weather_col:
            weather_series = project_df[weather_col].astype(str).str.strip()
            weather_cleaned = weather_series[~weather_series.str.lower().isin(["", "nan", "none", "n/a"])]

            if not weather_cleaned.empty:
                weather_palette = {
                    "Clear / Sunny": "#FFC107",
                    "Sunny": "#FFC107",
                    "Partly Cloudy": "#90CAF9",
                    "Overcast": "#78909C",
                    "Cloudy": "#78909C",
                    "Light Rain": "#42A5F5",
                    "Rain": "#1E88E5",
                    "Heavy Rain / Storm": "#1565C0",
                    "Snow": "#E0F7FA",
                    "Windy": "#B0BEC5",
                    "Extreme Heat": "#FF5722",
                    "Extreme Cold": "#00BCD4"
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
            else:
                st.info(f"Column '{weather_col}' found, but no weather entries logged yet.")
        else:
            st.warning(
                f"No column containing 'Weather' found. Available columns in your sheet: {list(project_df.columns)}")

# --- TAB 4: Raw Data Table ---
with tab_raw:
    st.subheader("Raw Submission Table")
    st.dataframe(filtered_df, use_container_width=True)

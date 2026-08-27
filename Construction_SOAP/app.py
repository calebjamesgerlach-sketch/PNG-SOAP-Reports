import streamlit as st
import pandas as pd
import gspread
import plotly.express as px

# 1. Page Configuration (Must always be first)
st.set_page_config(page_title="Construction SOAP Dashboard", layout="wide")

st.title("Jobsite Daily SOAP Tracker")

@st.cache_data(ttl=60)  # Caches data for 60 seconds, then auto-refreshes
def load_data():
    gc = gspread.service_account(filename="credentials.json")
    sheet = gc.open("SOAP_Daily_Logs").sheet1
    records = sheet.get_all_records()
    df = pd.DataFrame(records)
    return df


# Fetch data
with st.spinner("Connecting to Google Sheets..."):
    try:
        df = load_data()
        st.success(f"Data synchronized successfully. Total logs: {len(df)}")
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        st.stop()

# --- Top-level KPI Metrics ---
col1, col2, col3 = st.columns(3)

# 1. Date filter setup (Last 7 Days)
log_dates = pd.to_datetime(df["Current Date"], errors="coerce")
cutoff_date = pd.Timestamp.now() - pd.Timedelta(days=7)
mask_7d = log_dates >= cutoff_date

# 2. Total vs 7-Day Reports
total_logs = len(df)
logs_7d = int(mask_7d.sum())

# 3. Total vs 7-Day Man-Hours
numeric_hours = pd.to_numeric(df["Man Hours"], errors="coerce").fillna(0)
total_hours = numeric_hours.sum()
hours_7d = numeric_hours[mask_7d].sum()

# 4. Total vs 7-Day Equipment / Tools Count
def count_tools(series):
    # Splits comma-separated tools, strips whitespace, filters out blanks and "None"
    all_tools = []
    for item in series.dropna():
        tools = [t.strip() for t in str(item).split(",") if t.strip() and t.strip().lower() != "none"]
        all_tools.extend(tools)
    return len(all_tools)

equip_series = df.get("Equipment Used", pd.Series())
total_tools_count = count_tools(equip_series)
tools_7d_count = count_tools(equip_series[mask_7d])

# 5. Render Metric Cards
col1.metric(
    label="Total Reports Logged",
    value=total_logs,
    delta=f"{logs_7d} in last 7 days",
    delta_color="off"
)

col2.metric(
    label="Total Man-Hours Logged",
    value=f"{total_hours:,.1f} hrs",
    delta=f"{hours_7d:,.1f} hrs in last 7 days",
    delta_color="off"
)

col3.metric(
    label="Total Equipment Deployed",
    value=total_tools_count,
    delta=f"{tools_7d_count} in last 7 days",
    delta_color="off"
)

st.markdown("---")

# Sidebar Filters
st.sidebar.header("Filter Logs")
projects = ["All"] + list(df["Project Name"].dropna().unique())
selected_project = st.sidebar.selectbox("Select Project", projects)

filtered_df = df if selected_project == "All" else df[df["Project Name"] == selected_project]

# Tab Layout: Data Table vs CQI Analytics vs Detailed SOAP View
tab_soap, tab_analytics, tab_raw = st.tabs(["📋 SOAP Report Viewer", "📊 CQI Analytics", "📁 Raw Data Table"])

with tab_soap:
    st.subheader("Field SOAP Entries")
    for idx, row in filtered_df.iterrows():
        with st.expander(
                f"📅 {row.get('Current Date', 'N/A')} - {row.get('Project Name', 'Unknown')} (By: {row.get('Name and Title', 'Unknown')})"):
            c1, c2, c3 = st.columns(3)
            c1.write(f"**Location:** {row.get('Location Address', 'N/A')}")
            c2.write(f"**Travel Time:** {row.get('Travel Time', 'N/A')}")
            c3.write(f"**Man Hours:** {row.get('Man Hours', 'N/A')} hrs")

            st.markdown("#### Clinical Site Breakdown (SOAP)")
            st.info(f"**S (Subjective):**\n{row.get('Subjective', 'No entries logged.')}")
            st.write(f"**O (Objective):**\n{row.get('Objective', 'No entries logged.')}")
            st.warning(f"**A (Assessment / QC / Safety):**\n{row.get('Assessment', 'No entries logged.')}")
            st.success(f"**P (Plan / Next Steps):**\n{row.get('Plan', 'No entries logged.')}")

with tab_analytics:
    st.subheader("Continuous Quality Improvement (CQI) Metrics")
    if not filtered_df.empty:
        # Row 1: Man-Hours and Tools Deployed by Project
        c1, c2 = st.columns(2)

        # 1. Man-Hours by Project
        fig_hours = px.bar(
            filtered_df,
            x="Project Name",
            y=pd.to_numeric(filtered_df["Man Hours"], errors="coerce"),
            title="Total Man-Hours by Project",
            labels={"y": "Hours", "Project Name": "Project"}
        )
        c1.plotly_chart(fig_hours, use_container_width=True)

        # 2. Total Tools/Equipment Deployed per Project
        tool_records = []
        for _, row in filtered_df.iterrows():
            proj = row.get("Project Name", "Unknown")
            raw_tools = str(row.get("Equipment Used", ""))
            if raw_tools and raw_tools.lower() not in ["nan", "none", ""]:
                for tool in raw_tools.split(","):
                    tool_clean = tool.strip()
                    if tool_clean and tool_clean.lower() != "none":
                        tool_records.append({"Project Name": proj, "Tool": tool_clean})

        if tool_records:
            df_tools = pd.DataFrame(tool_records)
            tools_by_proj = df_tools.groupby("Project Name").size().reset_index(name="Total Tools Deployed")
            fig_proj_tools = px.bar(
                tools_by_proj,
                x="Total Tools Deployed",
                y="Project Name",
                orientation="h",
                title="Total Tools & Equipment Deployed by Project",
                text="Total Tools Deployed"
            )
            fig_proj_tools.update_traces(textposition="outside")
            c2.plotly_chart(fig_proj_tools, use_container_width=True)
        else:
            c2.info("No tool/equipment deployments recorded for this selection.")

        st.markdown("---")

        # Row 2: Weather Distribution Pie Chart
        # Auto-detect column containing 'weather'
        weather_col = next((col for col in filtered_df.columns if "weather" in col.lower()), None)

        if weather_col:
            weather_series = filtered_df[weather_col].astype(str).str.strip()
            # Filter out blanks, nulls, and nan
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
            # Fallback: shows your exact available columns so you can verify the header name
            st.warning(f"No column containing 'Weather' found. Available columns in your sheet: {list(filtered_df.columns)}")

with tab_raw:
    st.subheader("Raw Submission Table")
    st.dataframe(filtered_df, use_container_width=True)
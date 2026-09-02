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


# --- Shared Helpers: Deduplicated Equipment Extraction ---
def extract_unique_tools_df(dataset):
    """
    Extracts all tool records and deduplicates by (Project Name, Current Date, Tool).
    If multiple reports are filed for the same project on the same day with the same tool,
    it is only counted once.
    """
    tool_records = []
    for _, row in dataset.iterrows():
        proj = str(row.get("Project Name", "Unknown")).strip()
        date = str(row.get("Current Date", "Unknown")).strip()
        raw_tools = str(row.get("Equipment Used", ""))
        
        if raw_tools and raw_tools.lower() not in ["nan", "none", ""]:
            for tool in raw_tools.split(","):
                tool_clean = tool.strip()
                if tool_clean and tool_clean.lower() != "none":
                    tool_records.append({
                        "Project Name": proj,
                        "Current Date": date,
                        "Tool": tool_clean
                    })
    
    if not tool_records:
        return pd.DataFrame(columns=["Project Name", "Current Date", "Tool"])
    
    raw_df = pd.DataFrame(tool_records)
    # Drop duplicates per project, date, and tool
    deduped_df = raw_df.drop_duplicates(subset=["Project Name", "Current Date", "Tool"])
    return deduped_df


def count_unique_tools(dataset):
    return len(extract_unique_tools_df(dataset))


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

    # Deduplicated equipment counts
    total_tools_count = count_unique_tools(df)
    tools_7d_count = count_unique_tools(df[mask_7d])

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

    # Tabs
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
            p_tools = count_unique_tools(project_df)
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

            df_tools = extract_unique_tools_df(project_df)
            if not df_tools.empty:
                tools_summary = df_tools.groupby("Tool").size().reset_index(name="Count").sort_values(by="Count", ascending=False)
                fig_proj_tools = px.bar(
                    tools_summary.head(10),
                    x="Count",
                    y="Tool",
                    orientation="h",
                    title="Top Equipment Used (Unique per Day/Project)",
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
# DASHBOARD 2: CREW (Personnel & Pay Period Hours)
# =========================================================
elif dashboard_view == "👷 Crew":
    crew_df = df.copy()
    crew_df["Numeric_Hours"] = pd.to_numeric(crew_df.get("Man Hours", 0), errors="coerce").fillna(0)
    crew_df["Submitter"] = crew_df.get("Name and Title", "Unknown").astype(str).str.strip()

    # Drop records with invalid or missing dates for accurate period filtering
    valid_dates_df = crew_df.dropna(subset=["Parsed Date"]).copy()

    # Create Month identifier (e.g., '2026-08') and Day of Month
    valid_dates_df["Year_Month"] = valid_dates_df["Parsed Date"].dt.strftime("%Y-%m")
    valid_dates_df["Day"] = valid_dates_df["Parsed Date"].dt.day

    # Categorize into pay periods: 1st–15th and 16th–End
    valid_dates_df["Pay_Period"] = valid_dates_df["Day"].apply(
        lambda d: "1st – 15th" if d <= 15 else "16th – End"
    )

    # Top Month Selector
    available_months = sorted(valid_dates_df["Year_Month"].unique(), reverse=True)
    
    if available_months:
        selected_month = st.selectbox("Select Month for Pay Period Breakdown", available_months)
        month_filtered_df = valid_dates_df[valid_dates_df["Year_Month"] == selected_month].copy()
    else:
        selected_month = "No Data"
        month_filtered_df = valid_dates_df.copy()

    # Calculate Period Hours for Selected Month
    p1_hours = month_filtered_df[month_filtered_df["Pay_Period"] == "1st – 15th"]["Numeric_Hours"].sum()
    p2_hours = month_filtered_df[month_filtered_df["Pay_Period"] == "16th – End"]["Numeric_Hours"].sum()
    month_total_hours = p1_hours + p2_hours

    # Metrics Row
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Total Hours ({selected_month})", f"{month_total_hours:,.1f} hrs")
    c2.metric("Period 1 (1st – 15th)", f"{p1_hours:,.1f} hrs")
    c3.metric("Period 2 (16th – End)", f"{p2_hours:,.1f} hrs")

    st.markdown("---")
    st.subheader(f"Crew Hours Breakdown by Half-Month ({selected_month})")

    if not month_filtered_df.empty:
        # Pivot table: Submitter x Pay_Period
        pivot_periods = month_filtered_df.pivot_table(
            index="Submitter",
            columns="Pay_Period",
            values="Numeric_Hours",
            aggfunc="sum",
            fill_value=0
        ).reset_index()

        # Ensure both columns exist even if no logs are in one period
        if "1st – 15th" not in pivot_periods.columns:
            pivot_periods["1st – 15th"] = 0.0
        if "16th – End" not in pivot_periods.columns:
            pivot_periods["16th – End"] = 0.0

        pivot_periods["Total Month Hours"] = pivot_periods["1st – 15th"] + pivot_periods["16th – End"]
        pivot_periods = pivot_periods.sort_values(by="Total Month Hours", ascending=False)

        col_chart, col_table = st.columns([1.1, 0.9])

        with col_chart:
            # Grouped bar chart comparing periods per worker
            plot_df = month_filtered_df.groupby(["Submitter", "Pay_Period"])["Numeric_Hours"].sum().reset_index()
            fig_period = px.bar(
                plot_df,
                x="Submitter",
                y="Numeric_Hours",
                color="Pay_Period",
                barmode="group",
                title=f"Hours per Pay Period by Crew Member ({selected_month})",
                labels={"Numeric_Hours": "Hours", "Submitter": "Crew Member", "Pay_Period": "Period"},
                color_discrete_map={"1st – 15th": "#3b82f6", "16th – End": "#10b981"}
            )
            fig_period.update_layout(legend_title_text="")
            st.plotly_chart(fig_period, use_container_width=True)

        with col_table:
            st.write("#### Pay Period Summary Table")
            display_table = pivot_periods.rename(columns={
                "Submitter": "Crew Member",
                "1st – 15th": "1st – 15th (Hrs)",
                "16th – End": "16th – End (Hrs)",
                "Total Month Hours": "Month Total (Hrs)"
            })
            st.dataframe(
                display_table.style.format({
                    "1st – 15th (Hrs)": "{:.1f}",
                    "16th – End (Hrs)": "{:.1f}",
                    "Month Total (Hrs)": "{:.1f}"
                }),
                use_container_width=True
            )
    else:
        st.info("No dated entries logged for this month.")


# =========================================================
# DASHBOARD 3: EQUIPMENT (Tools & Deployment Metrics)
# =========================================================
elif dashboard_view == "🛠️ Equipment":
    df_tools = extract_unique_tools_df(df)

    total_tool_deployments = len(df_tools)
    
    if not df_tools.empty:
        tool_counts = df_tools["Tool"].value_counts()
        most_used_tool = tool_counts.index[0]
        most_used_count = tool_counts.iloc[0]

        project_tool_counts = df_tools["Project Name"].value_counts()
        top_project_name = project_tool_counts.index[0]
        top_project_count = project_tool_counts.iloc[0]
    else:
        most_used_tool = "None"
        most_used_count = 0
        top_project_name = "None"
        top_project_count = 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Equipment Deployed", total_tool_deployments)
    c2.metric("Most Used Equipment", most_used_tool, delta=f"{most_used_count} site-days", delta_color="off")
    c3.metric("Top Equipment Project", top_project_name, delta=f"{top_project_count} site-days", delta_color="off")

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
                title="Equipment Frequency (Total Days on Site)",
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
                title="Equipment Days by Project",
                barmode="stack"
            )
            st.plotly_chart(fig_proj_tools, use_container_width=True)
    else:
        st.info("No equipment deployments recorded in any daily logs yet.")

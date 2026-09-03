import os
import json
import calendar
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
    return raw_df.drop_duplicates(subset=["Project Name", "Current Date", "Tool"])


def count_unique_tools(dataset):
    return len(extract_unique_tools_df(dataset))


def build_monthly_calendar_heatmap(date_series, year_month_str):
    year, month = map(int, year_month_str.split("-"))
    month_dates = pd.to_datetime(date_series).dropna()
    this_month_dates = month_dates[
        (month_dates.dt.year == year) & (month_dates.dt.month == month)
    ]
    day_counts = this_month_dates.dt.day.value_counts().to_dict()

    cal = calendar.Calendar(firstweekday=0)
    month_cal = cal.monthdayscalendar(year, month)

    z_matrix = []
    text_matrix = []
    hover_matrix = []

    for week in month_cal:
        z_row = []
        text_row = []
        hover_row = []
        for day in week:
            if day == 0:
                z_row.append(None)
                text_row.append("")
                hover_row.append("")
            else:
                count = day_counts.get(day, 0)
                z_row.append(count)
                text_row.append(f"<b>{day}</b><br>{count} logs" if count > 0 else f"<b>{day}</b>")
                hover_row.append(f"Date: {year}-{month:02d}-{day:02d}<br>Reports Filed: {count}")
        z_matrix.append(z_row)
        text_matrix.append(text_row)
        hover_matrix.append(hover_row)

    days_header = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    week_labels = [f"W{i + 1}" for i in range(len(month_cal))]

    fig = px.imshow(
        z_matrix,
        x=days_header,
        y=week_labels,
        color_continuous_scale="Reds",
        labels={"color": "Reports Logged"},
        title=f"Activity & Filing Heatmap — {calendar.month_name[month]} {year}",
    )

    fig.update_traces(
        text=text_matrix,
        texttemplate="%{text}",
        hovertext=hover_matrix,
        hoverinfo="text",
        textfont_size=12,
        xgap=4,
        ygap=4,
    )

    fig.update_layout(
        height=340,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis=dict(side="top"),
        yaxis=dict(autorange="reversed", showticklabels=False),
        coloraxis_colorbar=dict(title="Reports", thickness=14, len=0.8),
    )
    return fig


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
    # 1. State Persistence setup
    if "saved_all_time_state" not in st.session_state:
        st.session_state["saved_all_time_state"] = True

    def on_toggle_change():
        st.session_state["saved_all_time_state"] = st.session_state["analytics_all_time_widget"]

    # 2. Extract unique available months
    valid_dates = df["Parsed Date"].dropna()
    available_months = sorted(valid_dates.dt.strftime("%Y-%m").unique(), reverse=True) if not valid_dates.empty else []

    # 3. Controls UI: Centered Month Picker + All-Time Toggle
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1, 1.3, 1])

    with ctrl_col2:
        sub_c1, sub_c2 = st.columns([1.2, 1])
        with sub_c2:
            st.write("")
            st.write("")
            all_time_toggle = st.toggle(
                "View All-Time",
                value=st.session_state["saved_all_time_state"],
                key="analytics_all_time_widget",
                on_change=on_toggle_change
            )

        with sub_c1:
            if available_months:
                selected_month = st.selectbox(
                    "Filter by Specific Month",
                    available_months,
                    disabled=all_time_toggle,
                    key="analytics_month_picker"
                )
            else:
                selected_month = None
                st.selectbox("Filter by Specific Month", ["No Data"], disabled=True)

    # 4. Scope the dataframe based on user choice
    if all_time_toggle or not selected_month:
        scoped_df = df.copy()
        time_label = "All-Time"
    else:
        scoped_df = df[df["Parsed Date"].dt.strftime("%Y-%m") == selected_month].copy()
        time_label = f"Month: {selected_month}"

    st.markdown("---")

    # Macro KPIs
    col1, col2, col3 = st.columns(3)
    cutoff_date = pd.Timestamp.now() - pd.Timedelta(days=7)
    mask_7d = scoped_df["Parsed Date"] >= cutoff_date

    total_logs = len(scoped_df)
    logs_7d = int(mask_7d.sum())

    numeric_hours = pd.to_numeric(scoped_df.get("Man Hours", 0), errors="coerce").fillna(0)
    total_hours = numeric_hours.sum()
    hours_7d = numeric_hours[mask_7d].sum()

    total_tools_count = count_unique_tools(scoped_df)
    tools_7d_count = count_unique_tools(scoped_df[mask_7d])

    col1.metric(f"Total Reports Logged ({time_label})", total_logs, delta=f"{logs_7d} in last 7 days", delta_color="off")
    col2.metric(f"Total Man-Hours Logged ({time_label})", f"{total_hours:,.1f} hrs", delta=f"{hours_7d:,.1f} hrs in last 7 days", delta_color="off")
    col3.metric(f"Total Equipment Deployed ({time_label})", total_tools_count, delta=f"{tools_7d_count} in last 7 days", delta_color="off")

    st.markdown("---")

    # Sidebar Filter: Project Umbrella
    st.sidebar.header("Navigation & Filters")
    project_list = ["All"] + sorted([p for p in scoped_df["Project Name"].dropna().unique() if str(p).strip()])
    selected_project = st.sidebar.selectbox("Select Project (Umbrella)", project_list)

    if selected_project == "All":
        project_df = scoped_df.copy()
    else:
        project_df = scoped_df[scoped_df["Project Name"] == selected_project].copy()

    # Tabs
    tab_umbrella_summary, tab_analytics, tab_raw = st.tabs([
        "🏢 Project Master Roll-Up",
        "📊 CQI Analytics",
        "📁 Raw Data Table"
    ])

    with tab_umbrella_summary:
        if selected_project == "All":
            st.subheader(f"All Projects Overview ({time_label})")
            if not scoped_df.empty:
                summary_table = scoped_df.groupby("Project Name").agg(
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
                st.info("No records found for this time period.")
        else:
            st.subheader(f"Master Summary for Project: {selected_project} ({time_label})")
            p_hours = pd.to_numeric(project_df.get("Man Hours", 0), errors="coerce").fillna(0).sum()
            p_tools = count_unique_tools(project_df)
            p_entries = len(project_df)

            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Total Daily Reports on File", p_entries)
            mc2.metric("Cumulative Project Man-Hours", f"{p_hours:,.1f} hrs")
            mc3.metric("Total Equipment Deployments", p_tools)

            st.markdown("---")
            st.markdown(f"### Cumulative Safety & QC Log ({time_label})")
            assess_df = project_df.dropna(subset=["Assessment"]).sort_values(by="Parsed Date", ascending=False)
            has_notes = False
            for _, a_row in assess_df.iterrows():
                if str(a_row["Assessment"]).strip() and str(a_row["Assessment"]).lower() != "no entries logged.":
                    st.warning(f"**{a_row.get('Current Date')} (by {a_row.get('Name and Title', 'Crew')}):**\n{a_row.get('Assessment')}")
                    has_notes = True
            if not has_notes:
                st.info("No safety or QC assessment logs recorded for this selection.")

    with tab_analytics:
        st.subheader(f"Continuous Quality Improvement (CQI) Metrics ({time_label})")
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

            # Monthly Activity Calendar
            st.markdown("---")
            st.subheader("🗓️ Daily Activity Calendar")

            cal_target_month = selected_month if (not all_time_toggle and selected_month) else (available_months[0] if available_months else None)
            if cal_target_month:
                cal_fig = build_monthly_calendar_heatmap(project_df["Parsed Date"], cal_target_month)
                st.plotly_chart(cal_fig, use_container_width=True)
                st.caption(f"🔴 **Activity Heatmap for {cal_target_month}:** Darker red indicates higher report volume on that day. White cells indicate zero reports or days off.")
            else:
                st.info("No dates available to generate calendar.")
        else:
            st.info("No logs found matching this time period and project filter.")

    with tab_raw:
        st.subheader(f"Raw Submission Table ({time_label})")
        st.dataframe(project_df, use_container_width=True)


# =========================================================
# DASHBOARD 2: CREW (Personnel & Pay Period Hours)
# =========================================================
elif dashboard_view == "👷 Crew":
    crew_df = df.copy()
    crew_df["Numeric_Hours"] = pd.to_numeric(crew_df.get("Man Hours", 0), errors="coerce").fillna(0)
    crew_df["Submitter"] = crew_df.get("Name and Title", "Unknown").astype(str).str.strip()

    valid_dates_df = crew_df.dropna(subset=["Parsed Date"]).copy()
    valid_dates_df["Year_Month"] = valid_dates_df["Parsed Date"].dt.strftime("%Y-%m")
    valid_dates_df["Day"] = valid_dates_df["Parsed Date"].dt.day
    valid_dates_df["Pay_Period"] = valid_dates_df["Day"].apply(
        lambda d: "1st – 15th" if d <= 15 else "16th – End"
    )

    available_months = sorted(valid_dates_df["Year_Month"].unique(), reverse=True)
    
    if available_months:
        selected_month = st.selectbox("Select Month for Pay Period Breakdown", available_months)
        month_filtered_df = valid_dates_df[valid_dates_df["Year_Month"] == selected_month].copy()
    else:
        selected_month = "No Data"
        month_filtered_df = valid_dates_df.copy()

    p1_hours = month_filtered_df[month_filtered_df["Pay_Period"] == "1st – 15th"]["Numeric_Hours"].sum()
    p2_hours = month_filtered_df[month_filtered_df["Pay_Period"] == "16th – End"]["Numeric_Hours"].sum()
    month_total_hours = p1_hours + p2_hours

    c1, c2, c3 = st.columns(3)
    c1.metric(f"Total Hours ({selected_month})", f"{month_total_hours:,.1f} hrs")
    c2.metric("Period 1 (1st – 15th)", f"{p1_hours:,.1f} hrs")
    c3.metric("Period 2 (16th – End)", f"{p2_hours:,.1f} hrs")

    st.markdown("---")
    st.subheader(f"Crew Hours Breakdown by Half-Month ({selected_month})")

    if not month_filtered_df.empty:
        pivot_periods = month_filtered_df.pivot_table(
            index="Submitter",
            columns="Pay_Period",
            values="Numeric_Hours",
            aggfunc="sum",
            fill_value=0
        ).reset_index()

        if "1st – 15th" not in pivot_periods.columns:
            pivot_periods["1st – 15th"] = 0.0
        if "16th – End" not in pivot_periods.columns:
            pivot_periods["16th – End"] = 0.0

        pivot_periods["Total Month Hours"] = pivot_periods["1st – 15th"] + pivot_periods["16th – End"]
        pivot_periods = pivot_periods.sort_values(by="Total Month Hours", ascending=False)

        col_chart, col_table = st.columns([1.1, 0.9])

        with col_chart:
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
    c1.metric("Total Equipment Days Deployed", total_tool_deployments)
    c2.metric("Most Used Equipment", most_used_tool, delta=f"{most_used_count} site-days", delta_color="off")
    c3.metric("Top Equipment Project", top_project_name, delta=f"{top_project_count} equipment-days", delta_color="off")

    st.markdown("---")
    st.subheader("Equipment Usage & Allocation (Deduplicated per Day)")

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

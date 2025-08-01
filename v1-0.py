import streamlit as st
import pandas as pd
import os
import re
from datetime import datetime
import webbrowser

# Constants
days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
day_lookup = {'M': 'Monday', 'T': 'Tuesday', 'W': 'Wednesday', 'R': 'Thursday', 'F': 'Friday'}

level_colors = {
    'Freshman': '#A6CEE3',
    'Sophomore': '#B2DF8A',
    'Junior': '#FDBF6F',
    'Senior': '#CAB2D6',
    'Graduate': '#FB9A99'
}

legend_html = """
<div style='margin-bottom:20px;'>
    <h3 style='margin-bottom:10px;'>Legend</h3>
    <div style='display:flex; gap:15px; flex-wrap:wrap;'>""" + \
    "".join([
        f"<div style='display:flex; align-items:center; gap:6px;'><div style='width:20px; height:20px; background:{color}; border:1px solid #555;'></div>{level}</div>"
        for level, color in level_colors.items()
    ]) + \
    "</div></div>"

# --------------------------
# Helpers and Rules
# --------------------------
def parse_meeting_pattern(pattern):
    match = re.match(r"([MTWRF]+)\s+(\d{1,2}(?::\d{2})?[ap]m)-(\d{1,2}(?::\d{2})?[ap]m)", str(pattern), re.IGNORECASE)
    if match:
        return pd.Series([*match.groups()])
    return pd.Series([None, None, None])

def to_datetime_time_safe(time_str):
    if pd.isna(time_str): return None
    try:
        return datetime.strptime(time_str.strip(), '%I:%M%p').time()
    except ValueError:
        return datetime.strptime(time_str.strip(), '%I%p').time()

def time_overlap(start1, end1, start2, end2):
    return max(start1, start2) < min(end1, end2)

def get_course_level(num):
    if pd.isna(num): return 'Unknown'
    if 100 <= num < 200: return 'Freshman'
    if 200 <= num < 300: return 'Sophomore'
    if 300 <= num < 400: return 'Junior'
    if 400 <= num < 500: return 'Senior'
    if 500 <= num < 800: return 'Graduate'
    return 'Unknown'

def violates_custom_rule(r1, r2, rules):
    for dept, level in rules:
        if (
            r1['Department'] == dept and int(r1['Course Number']) // 100 == level // 100 and
            r2['Department'] == dept and int(r2['Course Number']) // 100 == level // 100
        ):
            return True
    return False

# --------------------------
# HTML Generator
# --------------------------
def generate_html_site(df_calendar, output_path, rules=[]):
    os.makedirs(output_path, exist_ok=True)

    df_calendar['StartTimeObj'] = df_calendar['Start Time'].apply(to_datetime_time_safe)
    df_calendar['EndTimeObj'] = df_calendar['End Time'].apply(to_datetime_time_safe)
    df_calendar['Level Color'] = df_calendar['Course Level'].map(level_colors)
    df_calendar.dropna(subset=['StartTimeObj', 'EndTimeObj'], inplace=True)

    dept_files = {}
    for dept, group in df_calendar.groupby('Department'):
        g = group.copy()
        g['Days'] = g['Days'].apply(lambda x: [day_lookup[d] for d in x if d in day_lookup])
        g = g.explode('Days').reset_index(drop=True)

        g['Clash'] = False
        g['Clash Details'] = ""
        for i, row_i in g.iterrows():
            for j, row_j in g.iterrows():
                if i >= j or row_i['Days'] != row_j['Days']:
                    continue
                if time_overlap(row_i['StartTimeObj'], row_i['EndTimeObj'], row_j['StartTimeObj'], row_j['EndTimeObj']):
                    g.at[i, 'Clash'] = True
                    g.at[j, 'Clash'] = True
                    g.at[i, 'Clash Details'] += f"Clashes with {row_j['Course']} ({row_j['Course Level']}) {row_j['Start Time']}-{row_j['End Time']}; "
                    g.at[j, 'Clash Details'] += f"Clashes with {row_i['Course']} ({row_i['Course Level']}) {row_i['Start Time']}-{row_i['End Time']}; "

        html = f"""<html><head><title>{dept} Calendar</title><style>
        body {{ font-family: Arial; background: #f9f9f9; padding: 20px; }}
        h1 {{ text-align: center; color: #002855; }}
        .calendar {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }}
        .day-column {{ padding: 10px; background: #fff; border-radius: 8px; border: 1px solid #ccc; }}
        .event {{ margin: 10px 0; padding: 10px; border-radius: 5px; border-left: 4px solid #333; }}
        .clash {{ background-color: #ffcccc; border-left: 4px solid red; }}
        .event-time {{ font-weight: bold; }}
        a.back-link {{ display:inline-block; margin-bottom:20px; text-decoration:none; font-size:16px; color:#004B87; }}
        </style></head><body>
        <a href="calendar_directory.html" class="back-link">← Back to Directory</a>
        <h1>{dept} Course Calendar</h1>
        {legend_html}
        <div class='calendar'>"""

        for day in days_order:
            html += f"<div class='day-column'><h3>{day}</h3>"
            for _, row in g[g['Days'] == day].sort_values('StartTimeObj').iterrows():
                style_class = "event clash" if row['Clash'] else "event"
                html += f"<div class='{style_class}' style='background-color:{row['Level Color']}'>"
                html += f"<div class='event-time'>{row['Start Time']} - {row['End Time']}</div>"
                html += f"{row['Course']} - {row['Course Title']} ({row['Course Level']})<br>Room: {row['Room']}<br>Section: {row['Section #']}"
                if row['Clash']:
                    html += f"<div class='clash-note'>{row['Clash Details']}</div>"
                html += "</div>"
            html += "</div>"
        html += "</div></body></html>"

        fname = f"{dept}_calendar.html"
        with open(os.path.join(output_path, fname), "w", encoding="utf-8") as f:
            f.write(html)
        dept_files[dept] = fname

    # Suggested Schedules Page
    with open(os.path.join(output_path, "suggested_schedules.html"), "w", encoding="utf-8") as f:
        f.write(f"""
        <html><head><title>Suggested</title>
        <style>
        body {{ font-family: Arial; padding: 20px; background: #f9f9f9; }}
        h1 {{ text-align: center; color: #002855; }}
        h2 {{ margin-top: 40px; color: #003366; }}
        .calendar {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 40px; }}
        .day-column {{ padding: 10px; background: #fff; border-radius: 8px; border: 1px solid #ccc; }}
        .event {{ margin: 10px 0; padding: 10px; border-radius: 5px; border-left: 4px solid #333; }}
        a.back-link {{ display:inline-block; margin-bottom:20px; text-decoration:none; font-size:16px; color:#004B87; }}
        </style></head><body>
        <a href="calendar_directory.html" class="back-link">← Back to Directory</a>
        <h1>Suggested Optimal Schedules</h1>
        {legend_html}
        """)

        for dept, group in df_calendar.groupby('Department'):
            g = group.copy()
            g['Days'] = g['Days'].apply(lambda x: [day_lookup[d] for d in x if d in day_lookup])
            g = g.explode('Days').reset_index(drop=True)
            
            keep = []
            for i, row_i in g.iterrows():
                conflict = False
                for j, row_j in g.iterrows():
                    if i >= j or row_i['Days'] != row_j['Days']:
                        continue
                    if time_overlap(row_i['StartTimeObj'], row_i['EndTimeObj'], row_j['StartTimeObj'], row_j['EndTimeObj']):
                        if violates_custom_rule(row_i, row_j, rules):
                            conflict = True
                            break
                if not conflict:
                    keep.append(i)
            g = g.loc[keep]

            f.write(f"<h2>{dept}</h2><div class='calendar'>")
            for day in days_order:
                f.write(f"<div class='day-column'><h4>{day}</h4>")
                for _, row in g[g['Days'] == day].sort_values('StartTimeObj').iterrows():
                    f.write(f"<div class='event' style='background:{row['Level Color']}'>"
                            f"<strong>{row['Start Time']} - {row['End Time']}</strong><br>"
                            f"{row['Course']} - {row['Course Title']} ({row['Course Level']})<br>"
                            f"Room: {row['Room']} | Section: {row['Section #']}</div>")
                f.write("</div>")
            f.write("</div>")
        f.write("</body></html>")

    # Directory Page
    with open(os.path.join(output_path, "calendar_directory.html"), "w", encoding="utf-8") as f:
        f.write("""
        <!DOCTYPE html>
        <html><head><title>WVU Department Calendars</title><style>
        body { font-family: 'Segoe UI', sans-serif; padding: 40px 20px; background: #f8f9fa; color: #002855; }
        h1 { text-align: center; font-size: 2.5em; margin-bottom: 30px; }
        .section-title { font-size: 1.8em; margin: 50px 0 20px; text-align: center; }
        .grid { display: flex; flex-wrap: wrap; justify-content: center; gap: 24px; }
        .card {
            background: #fff; border-radius: 12px; padding: 20px; width: 240px; text-align: center;
            text-decoration: none; color: #002855;
            box-shadow: 0 4px 10px rgba(0,0,0,0.08); border: 1px solid #EAAA00;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .card:hover {
            transform: translateY(-4px);
            box-shadow: 0 8px 16px rgba(0,0,0,0.1);
            background: #fffbe6;
        }
        </style></head><body>
        <h1>LCSEE Department Calendars</h1>
        <div class='section-title'>Based on the uploaded file</div><div class='grid'>""")
        for dept, fname in dept_files.items():
            f.write(f'<a class="card" href="{fname}" target="_blank">{dept}</a>')
        f.write("""
        </div><div class='section-title'>Suggested</div>
        <div class='grid'><a class='card' href='suggested_schedules.html' target='_blank'>Optimal Schedule</a></div>
        </body></html>""")

    return os.path.abspath(os.path.join(output_path, "calendar_directory.html"))

# --------------------------
# Streamlit App UI
# --------------------------
st.image("logo.png", width=150)
st.title("CourseSync")
st.markdown("##### Course Calendar Generator")
st.markdown("##### West Virginia University")
st.markdown("<br>", unsafe_allow_html=True) 
uploaded = st.file_uploader("Upload Excel file", type=['xlsx'])
if uploaded:
    df = pd.read_excel(uploaded)
    df[['Days', 'Start Time', 'End Time']] = df['Meeting Pattern'].apply(parse_meeting_pattern)
    df['Course Number'] = df['Course'].str.extract(r'(\d{3})').astype(float)
    df['Department'] = df['Course'].str.extract(r'^([A-Z]+)')
    df['Course Level'] = df['Course Number'].apply(get_course_level)
    df = df[df['Course Level'] != 'Unknown']
    df.reset_index(drop=True, inplace=True)

if st.button("Generate and View Calendars"):
    site_path = generate_html_site(df, "calendar_site", st.session_state.rule_list)
    st.success("Calendar generated!")

    # Load the suggested schedule HTML for download
    suggested_path = os.path.join("calendar_site", "suggested_schedules.html")
    with open(suggested_path, "rb") as f:
        html_bytes = f.read()

    # Download button
    st.download_button(
        label="⬇️ Download Optimal Schedule HTML",
        data=html_bytes,
        file_name="suggested_schedules.html",
        mime="text/html"
    )

    # Auto-open in browser
    webbrowser.open(f"file://{site_path}")
st.markdown("<br>", unsafe_allow_html=True) 
st.markdown("###### Scheduling rule to prevent overlapping courses at a specific level within a department (optional)")
with st.form("rule_form"):
    col1, col2 = st.columns(2)
    with col1:
        dept_input = st.text_input("Department", max_chars=4, placeholder="CS, EE, CPE etc.")
    with col2:
        level_input = st.selectbox("Level", [100, 200, 300, 400, 500, 600, 700])
    add_rule = st.form_submit_button("➕ Add Rule")
st.markdown("<br>", unsafe_allow_html=True) 
st.markdown(
    """
    <div style="position: center; bottom: 0; width: 100%; text-align: center; padding: 10px;">
        <p style="font-size: 12px; color: #FFF;">Queries: kamrul.hasan@mail.wvu.edu</p>
    </div>
    """, 
    unsafe_allow_html=True
)

if "rule_list" not in st.session_state:
    st.session_state.rule_list = []

if add_rule and dept_input and level_input:
    st.session_state.rule_list.append((dept_input.upper(), int(level_input)))

if st.session_state.rule_list:
    st.markdown("#### Active Rules:")
    for i, (dept, level) in enumerate(st.session_state.rule_list):
        cols = st.columns([6, 1])
        with cols[0]:
            st.write(f"• No {dept} {level} level courses at the same time")
        with cols[1]:
            if st.button("🗑️", key=f"remove_{i}"):
                st.session_state.rule_list.pop(i)
                st.rerun()

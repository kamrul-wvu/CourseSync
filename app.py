import streamlit as st
import pandas as pd
import numpy as np
import os
import re
from io import BytesIO
from datetime import datetime
from zipfile import ZipFile
from matplotlib.colors import to_rgb, to_hex
from collections import defaultdict
import webbrowser

# Constants
days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
day_lookup = {'M': 'Monday', 'T': 'Tuesday', 'W': 'Wednesday', 'R': 'Thursday', 'F': 'Friday'}

# Soft and eye-comfort colors (color-blind–friendly palette)
level_colors = {
    'Freshman': '#A6CEE3',
    'Sophomore': '#B2DF8A',
    'Junior': '#FDBF6F',
    'Senior': '#CAB2D6',
    'Graduate': '#FB9A99'
}

# Helpers
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

def generate_html_site(df_calendar, output_path):
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

        legend_html = "<div style='margin: 20px 0; padding: 10px; background: #eee; border-radius: 5px;'>"
        legend_html += "<h3>Legend</h3><ul style='list-style: none; padding: 0; display: flex; gap: 20px; flex-wrap: wrap;'>"
        for level, color in level_colors.items():
            legend_html += f"<li style='display: flex; align-items: center;'><div style='width: 20px; height: 20px; background:{color}; margin-right: 8px; border: 1px solid #aaa;'></div>{level}</li>"
        legend_html += "</ul></div>"

        html = f"""
        <html><head><title>{dept} Calendar</title>
        <style>
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
        <div class='calendar'>
        """
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

    # Suggested Schedules page
    with open(os.path.join(output_path, "suggested_schedules.html"), "w", encoding="utf-8") as f:
        f.write("""
        <html><head><title>Suggested Schedules</title>
        <style>
            body { font-family: Arial; padding: 20px; background: #f9f9f9; }
            h1 { text-align: center; color: #002855; }
            h2 { margin-top: 40px; color: #003366; }
            .calendar { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 40px; }
            .day-column { padding: 10px; background: #fff; border-radius: 8px; border: 1px solid #ccc; }
            .event { margin: 10px 0; padding: 10px; border-radius: 5px; border-left: 4px solid #333; }
            a.back-link { display:inline-block; margin-bottom:20px; text-decoration:none; font-size:16px; color:#004B87; }
        </style></head><body>
        <a href="calendar_directory.html" class="back-link">← Back to Directory</a>
        <h1>Suggested Optimal Schedules (All Courses Included)</h1>
        """)

        for dept, group in df_calendar.groupby('Department'):
            g = group.copy()
            g['Days'] = g['Days'].apply(lambda x: [day_lookup[d] for d in x if d in day_lookup])
            g = g.explode('Days').reset_index(drop=True)

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

    # Directory page
    with open(os.path.join(output_path, "calendar_directory.html"), "w", encoding="utf-8") as f:
        f.write("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>WVU Department Calendars</title>
            <style>
                body { font-family: 'Segoe UI', sans-serif; padding: 40px 20px; background: #f8f9fa; color: #002855; }
                h1 { text-align: center; font-size: 2.5em; margin-bottom: 30px; }
                .section-title { font-size: 1.8em; margin: 50px 0 20px; text-align: center; }
                .grid { display: flex; flex-wrap: wrap; justify-content: center; gap: 24px; }
                .card {
                    background: #fff;
                    border-radius: 12px;
                    padding: 20px;
                    width: 240px;
                    text-align: center;
                    text-decoration: none;
                    color: #002855;
                    box-shadow: 0 4px 10px rgba(0,0,0,0.08);
                    transition: transform 0.2s ease, box-shadow 0.2s ease;
                    border: 1px solid #EAAA00;
                }
                .card:hover {
                    transform: translateY(-4px);
                    box-shadow: 0 8px 16px rgba(0,0,0,0.1);
                    background: #fffbe6;
                }
            </style>
        </head>
        <body>
            <h1>LCSEE Department Calendars</h1>
            <div class='section-title'>Department Calendars</div>
            <div class='grid'>
        """)
        for dept, fname in dept_files.items():
            f.write(f'<a class="card" href="{fname}" target="_blank">{dept}</a>')
        f.write("""
            </div>
            <div class='section-title'>Suggested Schedules</div>
            <div class='grid'>
                <a class='card' href='suggested_schedules.html' target='_blank'>Optimal Schedule</a>
            </div>
        </body></html>""")

    return os.path.abspath(os.path.join(output_path, "calendar_directory.html"))

# Streamlit app
st.title("CourseSync - WVU Course Calendar Generator")
uploaded = st.file_uploader("Upload Excel file", type=['xlsx'])

if uploaded:
    df = pd.read_excel(uploaded, sheet_name=0)
    df[['Days', 'Start Time', 'End Time']] = df['Meeting Pattern'].apply(parse_meeting_pattern)
    df['Course Number'] = df['Course'].str.extract(r'(\d+)').astype(float)
    df['Department'] = df['Course'].str.extract(r'^([A-Z]+)')
    df['Course Level'] = df['Course Number'].apply(get_course_level)
    df = df[df['Course Level'] != 'Unknown']
    df.reset_index(drop=True, inplace=True)

    if st.button("Generate and View Calendars"):
        site_path = generate_html_site(df, "calendar_site")
        st.success("Calendar generated!")
        st.markdown(f"[Click here to open calendar directory](file://{site_path})")
        webbrowser.open(f"file://{site_path}")

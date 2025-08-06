import streamlit as st
import pandas as pd
import os
import re
from datetime import datetime
from datetime import datetime, time
import webbrowser
from collections import defaultdict

# Constants
days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
day_lookup = {'M': 'Monday', 'T': 'Tuesday', 'W': 'Wednesday', 'R': 'Thursday', 'F': 'Friday'}

# --------------------------
# Helpers and Rules
# --------------------------

def to_datetime_time_safe(time_str):
    if pd.isna(time_str): return None
    time_str = str(time_str).strip().lower().replace(" ", "")
    for fmt in ['%I:%M%p', '%I%p']:
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            continue
    return None

def extract_course_level(course_str):
    match = re.search(r'\b(\d{3})[A-Z]?\b', str(course_str))
    return int(match.group(1)) if match else None

def time_overlap(start1, end1, start2, end2):
    return max(start1, start2) < min(end1, end2)

def parse_meeting_pattern(pattern):
    match = re.match(r"([MTWRF]+)\s+(\d{1,2}(?::\d{2})?[ap]m)-(\d{1,2}(?::\d{2})?[ap]m)", str(pattern).strip(), re.IGNORECASE)
    if match:
        return pd.Series([match.group(1), match.group(2), match.group(3)])
    return pd.Series([None, None, None])

# --------------------------
# Clash Report Generator
# --------------------------

def get_free_slots(df_dept_day, start_bound, end_bound):
    busy = sorted([(r['StartTimeObj'], r['EndTimeObj']) for _, r in df_dept_day.iterrows()])
    free = []
    current = start_bound

    for b_start, b_end in busy:
        if b_start > current:
            free.append((current, b_start))
        current = max(current, b_end)

    if current < end_bound:
        free.append((current, end_bound))

    return [
        (s, e) for s, e in free
        if (e.hour * 60 + e.minute) - (s.hour * 60 + s.minute) >= 50
    ]

def generate_clash_report(df_calendar, output_path="calendar_site/clash_report.html"):
    df_calendar[['Days', 'Start Time', 'End Time']] = df_calendar['Meeting Pattern'].apply(parse_meeting_pattern)
    df_calendar['StartTimeObj'] = df_calendar['Start Time'].apply(to_datetime_time_safe)
    df_calendar['EndTimeObj'] = df_calendar['End Time'].apply(to_datetime_time_safe)
    df_calendar['Department'] = df_calendar['Course'].str.extract(r'^([A-Z]+)')
    df_calendar.dropna(subset=['StartTimeObj', 'EndTimeObj'], inplace=True)

    clash_entries = []
    free_slots_by_dept = defaultdict(lambda: defaultdict(list))

    for dept, group in df_calendar.groupby('Department'):
        g = group.copy()
        g['Days'] = g['Days'].apply(lambda x: [day_lookup.get(d, d) for d in x if d in day_lookup])
        g = g.explode('Days').reset_index(drop=True)

        # Clash detection
        for i, row_i in g.iterrows():
            for j, row_j in g.iterrows():
                if i >= j or row_i['Days'] != row_j['Days']:
                    continue
                if time_overlap(row_i['StartTimeObj'], row_i['EndTimeObj'],
                                row_j['StartTimeObj'], row_j['EndTimeObj']):
                    level_i = extract_course_level(row_i['Course'])
                    level_j = extract_course_level(row_j['Course'])
                    if level_i is None or level_j is None:
                        continue
                    levels = sorted([level_i // 100, level_j // 100])
                    row_class = "red-row" if (levels == [3, 3] or levels == [3, 4] or levels == [4, 4] or
                                              levels == [5, 5] or levels == [5, 6] or levels == [6, 6] or
                                              levels == [6, 7]) else "green-row"
                    clash_entries.append({
                        "Department": dept,
                        "Course A": row_i['Course'], "Section A": row_i['Section #'],
                        "Course B": row_j['Course'], "Section B": row_j['Section #'],
                        "Time": f"{row_i['Start Time']}–{row_i['End Time']}",
                        "Day(s)": row_i['Days'],
                        "RowClass": row_class
                    })

        # Free slot calculation
        for day in days_order:
            g_day = g[g['Days'] == day]
            slots = get_free_slots(g_day, time(9, 0), time(20, 50))
            free_slots_by_dept[dept][day] = slots

    df_clashes = pd.DataFrame(clash_entries)
    grouped = (
        df_clashes.groupby(
            ["Department", "Course A", "Section A", "Course B", "Section B", "Time", "RowClass"]
        )['Day(s)']
        .apply(lambda x: ", ".join(sorted(set(x))))
        .reset_index()
        if not df_clashes.empty else pd.DataFrame(columns=["Department", "Course A", "Section A", "Course B", "Section B", "Time", "Day(s)", "RowClass"])
    )

    html = """<html><head><title>Course Clashes</title><style>
        body { font-family: Arial; padding: 20px; background: #f9f9f9; }
        h1 { text-align: center; color: #002855; }
        h2 { color: #003366; margin-top: 40px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ccc; }
        th { background-color: #004B87; color: white; }
        tr:nth-child(even) { background-color: #f2f2f2; }
        .red-row { background-color: #ffdddd !important; }
        .green-row { background-color: #ddffdd !important; }
    </style></head><body>
    <h1>Detected Course Clashes</h1>"""

    # Ensure CS and EE appear first
    all_departments = sorted(
        df_calendar['Department'].dropna().unique(),
        key=lambda x: (x not in ["CS", "EE"], x)
    )

    for dept in all_departments:
        html += f"<h2>{dept} Department</h2>"

        dept_group = grouped[grouped['Department'] == dept]

        # Free Slot Table
        html += "<h3>📆 Weekly Free Slot Overview (1-Hour Blocks)</h3>"
        html += "<table style='text-align:center; border-collapse:collapse;'><tr><th style='border:1px solid #aaa;'>Time</th>"
        html += "".join(f"<th style='border:1px solid #aaa;'>{day}</th>" for day in days_order)
        html += "</tr>"

        hour_slots = []
        t = time(9, 0)
        while (t.hour * 60 + t.minute) <= (20 * 60):  # until 8:00 PM
            end_minutes = (t.hour * 60 + t.minute) + 60
            end_hour, end_min = divmod(end_minutes, 60)
            end = time(end_hour, end_min)
            hour_slots.append((t, end))
            t = end

        for s, e in hour_slots:
            html += f"<tr><td style='border:1px solid #aaa;'>{s.strftime('%I:%M %p')}–{e.strftime('%I:%M %p')}</td>"
            for day in days_order:
                slot_found = any(
                    (fs <= s and fe >= e) or
                    (s == time(20, 0) and (fe.hour * 60 + fe.minute) - (fs.hour * 60 + fs.minute) >= 50 and fs <= s and fe >= s)
                    for fs, fe in free_slots_by_dept[dept][day]
                )
                html += f"<td style='border:1px solid #aaa; color:{'green' if slot_found else '#bbb'};'>{'✅' if slot_found else '—'}</td>"
            html += "</tr>"
        html += "</table>"

        # Clashes
        for label, color in [('Non-Acceptable Clashes', 'red-row'), ('Acceptable Clashes', 'green-row')]:
            section = dept_group[dept_group['RowClass'] == color]
            html += f"<h3>{label}</h3>"
            if not section.empty:
                html += "<table><tr><th>Course A</th><th>Section A</th><th>Course B</th><th>Section B</th><th>Day(s)</th><th>Time</th></tr>"
                for _, row in section.iterrows():
                    html += f"<tr class='{row['RowClass']}'><td>{row['Course A']}</td><td>{row['Section A']}</td><td>{row['Course B']}</td><td>{row['Section B']}</td><td>{row['Day(s)']}</td><td>{row['Time']}</td></tr>"
                html += "</table>"
            else:
                html += "<p>No clashes in this category.</p>"

    html += "</body></html>"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


# --------------------------
# Streamlit App UI
# --------------------------
st.image("logo.png", width=150)
st.title("CourseSync")
st.markdown("##### West Virginia University")
st.markdown("<br>", unsafe_allow_html=True)

st.markdown("### 📝 Notes")
st.markdown("""
- Upload file in Excel or CSV format only.
- Uploaded file must include the following columns: Course, Section #, Course Title, Meeting Pattern.
- Only courses that follow standard meeting patterns (day, time) are included.
- Once generated, click on download clash report and open the file on a browser.
- Red marked clashes are between 300 - 300, 300 - 400, 500 - 500, 500 - 600, 600 - 600, 600 -700 levels.
- Green marked clashes are less important.
- Free slots shown are 1 hour each, from 9 AM to 9 PM on weekdays.
""")

uploaded = st.file_uploader("Upload Course Schedule (Excel or CSV)", type=['xlsx', 'csv'])

if uploaded:
    try:
        if uploaded.name.endswith('.csv'):
            df = pd.read_csv(uploaded)
        else:
            df = pd.read_excel(uploaded, engine='openpyxl')  # ✅ specify engine
    except Exception as e:
        st.error(f"Error reading file: {e}")
        st.stop()

    df[['Days', 'Start Time', 'End Time']] = df['Meeting Pattern'].apply(parse_meeting_pattern)
    df['Course Number'] = df['Course'].str.extract(r'(\d{3})').astype(float)
    df['Department'] = df['Course'].str.extract(r'^([A-Z]+)')
    df.reset_index(drop=True, inplace=True)


if st.button(":gear: Process Schedule"):

    clash_path = generate_clash_report(df)
    if clash_path:
        with open(clash_path, "rb") as f:
            st.download_button("📑 Download Clash Report", data=f.read(), file_name="clash_report.html", mime="text/html")
    # Save paths in session state
    st.session_state.clash_path = clash_path
    st.session_state.generated = True

    st.success("Clash Report generated!")
    


st.markdown("<br>", unsafe_allow_html=True)
st.markdown("""
    <div style="position: center; bottom: 0; width: 100%; text-align: center; padding: 10px;">
        <p style="font-size: 12px; color: #FFF;">Queries: kamrul.hasan@mail.wvu.edu | 304 685 8910</p>
	<p style="font-size: 12px; color: #FFF;">Version: 1.0</p>
    </div>
    """, unsafe_allow_html=True)
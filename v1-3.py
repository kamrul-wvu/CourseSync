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

def generate_department_calendar_actual_timing(df):
    df[['Days', 'Start Time', 'End Time']] = df['Meeting Pattern'].apply(parse_meeting_pattern)
    df['StartTimeObj'] = df['Start Time'].apply(to_datetime_time_safe)
    df['EndTimeObj'] = df['End Time'].apply(to_datetime_time_safe)
    df['Department'] = df['Course'].str.extract(r'^([A-Z]+)')
    df = df.dropna(subset=['StartTimeObj', 'EndTimeObj'])

    calendar_by_dept = {}

    for dept in sorted(df['Department'].dropna().unique()):
        dept_df = df[df['Department'] == dept].copy()
        dept_df['Days'] = dept_df['Days'].apply(lambda x: [day_lookup.get(d, d) for d in x if d in day_lookup])
        dept_df = dept_df.explode('Days')

        # Build unique time slots using exact start-end pairs
        time_slots = sorted(set([
            f"{row['StartTimeObj'].strftime('%I:%M %p')}–{row['EndTimeObj'].strftime('%I:%M %p')}"
            for _, row in dept_df.iterrows()
        ]), key=lambda x: datetime.strptime(x.split("–")[0], "%I:%M %p"))

        schedule = pd.DataFrame(index=time_slots, columns=days_order)
        schedule.fillna("", inplace=True)

        for _, row in dept_df.iterrows():
            slot = f"{row['StartTimeObj'].strftime('%I:%M %p')}–{row['EndTimeObj'].strftime('%I:%M %p')}"
            day = row['Days']
            label = row['Course']
            existing = schedule.loc[slot, day]
            if existing:
                schedule.loc[slot, day] = existing + "<br>" + label
            else:
                schedule.loc[slot, day] = label

        calendar_by_dept[dept] = schedule

    return calendar_by_dept


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
    from datetime import time

    df_calendar[['Days', 'Start Time', 'End Time']] = df_calendar['Meeting Pattern'].apply(parse_meeting_pattern)
    df_calendar['StartTimeObj'] = df_calendar['Start Time'].apply(to_datetime_time_safe)
    df_calendar['EndTimeObj'] = df_calendar['End Time'].apply(to_datetime_time_safe)
    df_calendar['Department'] = df_calendar['Course'].str.extract(r'^([A-Z]+)')
    df_calendar.dropna(subset=['StartTimeObj', 'EndTimeObj'], inplace=True)

    clash_entries = []
    wednesday_4_5_clashes = []
    free_slots_by_dept = defaultdict(lambda: defaultdict(list))

    wednesday_restricted_start = time(16, 0)
    wednesday_restricted_end = time(17, 0)

    for dept, group in df_calendar.groupby('Department'):
        g = group.copy()
        g['Days'] = g['Days'].apply(lambda x: [day_lookup.get(d, d) for d in x if d in day_lookup])
        g = g.explode('Days').reset_index(drop=True)

        # Detect Wednesday 4–5PM restricted clashes
        wednesday_rows = g[g['Days'] == 'Wednesday']
        for _, row in wednesday_rows.iterrows():
            if time_overlap(row['StartTimeObj'], row['EndTimeObj'], wednesday_restricted_start, wednesday_restricted_end):
                wednesday_4_5_clashes.append({
                    "Department": dept,
                    "Course": row['Course'],
                    "Section": row['Section #'],
                    "Time": f"{row['Start Time']}–{row['End Time']}",
                    "Day": row['Days']
                })

        # Detect clashes
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

                    if row_i['Department'] == 'CSEE' or row_j['Department'] == 'CSEE':
                        row_class = "green-row"
                    else:
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

            # ❌ Exclude only the exact 4–5 PM slot on Wednesday
            if day == "Wednesday":
                slots = [s for s in slots if not (s[0] == wednesday_restricted_start and s[1] == wednesday_restricted_end)]

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

    all_departments = sorted(
        df_calendar['Department'].dropna().unique(),
        key=lambda x: (x not in ["CS", "EE"], x)
    )

    for dept in all_departments:
        html += f"<h2>{dept} Department</h2>"

        # 📅 Free Slot Table with 🔒 Lock
        html += "<h3>📆 Weekly Free Slot Overview (1-Hour Blocks)</h3>"
        html += "<table style='text-align:center; border-collapse:collapse;'><tr><th style='border:1px solid #aaa;'>Time</th>"
        html += "".join(f"<th style='border:1px solid #aaa;'>{day}</th>" for day in days_order)
        html += "</tr>"

        hour_slots = []
        t = time(9, 0)
        while (t.hour * 60 + t.minute) <= (20 * 60):
            end_minutes = (t.hour * 60 + t.minute) + 60
            end_hour, end_min = divmod(end_minutes, 60)
            end = time(end_hour, end_min)
            hour_slots.append((t, end))
            t = end

        for s, e in hour_slots:
            html += f"<tr><td style='border:1px solid #aaa;'>{s.strftime('%I:%M %p')}–{e.strftime('%I:%M %p')}</td>"
            for day in days_order:
                if day == "Wednesday" and s == wednesday_restricted_start and e == wednesday_restricted_end:
                    icon = "🔒"
                    color = "red"
                else:
                    slot_found = any(
                        (fs <= s and fe >= e) or
                        (s == time(20, 0) and (fe.hour * 60 + fe.minute) - (fs.hour * 60 + fs.minute) >= 50 and fs <= s and fe >= s)
                        for fs, fe in free_slots_by_dept[dept][day]
                    )
                    icon = "✅" if slot_found else "—"
                    color = "green" if slot_found else "#bbb"
                html += f"<td style='border:1px solid #aaa; color:{color};'>{icon}</td>"
            html += "</tr>"
        html += "</table>"

        # Clashes
        # 🔴 Special Table: Wednesday 4–5 PM Conflicts
        # 🔴 Wednesday 4–5 PM slot restricted courses
        dept_wed_clashes = [c for c in wednesday_4_5_clashes if c["Department"] == dept]
        if dept_wed_clashes:
            html += "<h3>⚠️ Wednesday 4:00–5:00 PM Restricted Slot Courses</h3>"
            html += f"<p style='color:red; font-weight:bold;'>🔴 {len(dept_wed_clashes)} Violations</p>"
            html += "<table><tr><th>Course</th><th>Section</th><th>Day</th><th>Time</th></tr>"
            for clash in dept_wed_clashes:
                html += f"<tr class='red-row'><td>{clash['Course']}</td><td>{clash['Section']}</td><td>{clash['Day']}</td><td>{clash['Time']}</td></tr>"
            html += "</table>"

        # 🔴🟢 Clash tables with violation counters
        dept_group = grouped[grouped['Department'] == dept]
        for label, color in [('Non-Acceptable Clashes', 'red-row'), ('Acceptable Clashes', 'green-row')]:
            section = dept_group[dept_group['RowClass'] == color]
            html += f"<h3>{label}</h3>"
            if not section.empty:
                count_label = f"<p style='color:{'red' if color == 'red-row' else 'green'}; font-weight:bold;'>"
                count_label += f"{'🔴' if color == 'red-row' else '🟢'} {len(section)} {'Violations' if color == 'red-row' else 'Accepted Clashes'}</p>"
                html += count_label
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

    # Count red (non-acceptable) clashes
    red_count = len(grouped[grouped["RowClass"] == "red-row"])
    # Count Wednesday 4–5 PM violations
    wed_count = len([c for c in wednesday_4_5_clashes])

    return output_path, {
        "non_acceptable": red_count,
        "wednesday_4_5": wed_count
    }


def generate_cross_dept_clash_report(df_calendar, output_path="calendar_site/cross_report.html"):
    df_calendar[['Days', 'Start Time', 'End Time']] = df_calendar['Meeting Pattern'].apply(parse_meeting_pattern)
    df_calendar['StartTimeObj'] = df_calendar['Start Time'].apply(to_datetime_time_safe)
    df_calendar['EndTimeObj'] = df_calendar['End Time'].apply(to_datetime_time_safe)
    df_calendar['Department'] = df_calendar['Course'].str.extract(r'^([A-Z]+)')
    df_calendar.dropna(subset=['StartTimeObj', 'EndTimeObj'], inplace=True)

    g = df_calendar.copy()
    g['Days'] = g['Days'].apply(lambda x: [day_lookup.get(d, d) for d in x if d in day_lookup])
    g = g.explode('Days').reset_index(drop=True)

    valid_depts = ["CS", "EE", "CPE"]
    clash_entries = []
    special_csee_clashes = []

    for i, row_i in g.iterrows():
        for j, row_j in g.iterrows():
            if i >= j or row_i['Days'] != row_j['Days']:
                continue

            dept_i, dept_j = row_i['Department'], row_j['Department']
            course_i, course_j = row_i['Course'], row_j['Course']
            level_i = extract_course_level(course_i)
            level_j = extract_course_level(course_j)

            if level_i is None or level_j is None:
                continue

            if not time_overlap(row_i['StartTimeObj'], row_i['EndTimeObj'], row_j['StartTimeObj'], row_j['EndTimeObj']):
                continue

            # 🔴 Special rule: CSEE 480S or 481S cannot clash with any 300/400-level course
            if (course_i in ["CSEE 480S", "CSEE 481S"] and 300 <= level_j < 500) or \
               (course_j in ["CSEE 480S", "CSEE 481S"] and 300 <= level_i < 500):
                special_csee_clashes.append({
                    "Course A": course_i, "Section A": row_i['Section #'],
                    "Course B": course_j, "Section B": row_j['Section #'],
                    "Time": f"{row_i['Start Time']}–{row_i['End Time']}",
                    "Day(s)": row_i['Days'],
                    "RowClass": "red-row"
                })
                continue

            # 🔴 CS/EE/CPE same-level (300–700) clashes
            if dept_i in valid_depts and dept_j in valid_depts and dept_i != dept_j:
                level_group_i = level_i // 100
                level_group_j = level_j // 100
                if 3 <= level_group_i <= 7 and level_group_i == level_group_j:
                    dept_pair = tuple(sorted([dept_i, dept_j]))
                    if dept_pair in [("CS", "EE"), ("CS", "CPE"), ("EE", "CPE")]:
                        clash_entries.append({
                            "DeptPair": dept_pair,
                            "Course A": course_i, "Section A": row_i['Section #'],
                            "Course B": course_j, "Section B": row_j['Section #'],
                            "Time": f"{row_i['Start Time']}–{row_i['End Time']}",
                            "Day(s)": row_i['Days'],
                            "RowClass": "red-row"
                        })

    df_clashes = pd.DataFrame(clash_entries)
    if not df_clashes.empty:
        grouped = df_clashes.groupby(
            ["DeptPair", "Course A", "Section A", "Course B", "Section B", "Time", "RowClass"]
        )['Day(s)'].apply(lambda x: ", ".join(sorted(set(x)))).reset_index()
    else:
        grouped = pd.DataFrame(columns=["DeptPair", "Course A", "Section A", "Course B", "Section B", "Time", "Day(s)", "RowClass"])

    html = """<html><head><title>Cross-Department Clashes</title><style>
    body { font-family: Arial; padding: 20px; background: #f9f9f9; }
    h1 { text-align: center; color: #002855; }
    h2 { color: #003366; margin-top: 40px; }
    table { width: 100%; border-collapse: collapse; margin-top: 10px; }
    th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ccc; }
    th { background-color: #004B87; color: white; }
    tr:nth-child(even) { background-color: #f2f2f2; }
    .red-row { background-color: #ffdddd !important; }
    </style></head><body>
    <h1>Cross-Department Clashes</h1>"""



    # 🔴 CS–EE, EE–CPE, CS–CPE Clashes with red violation count
    for pair in [('CS', 'EE'), ('EE', 'CPE'), ('CS', 'CPE')]:
        section = grouped[grouped['DeptPair'] == pair]
        html += f"<h2>{pair[0]} – {pair[1]} Same Level Clashes (300–700)</h2>"
        if not section.empty:
            html += f"<p style='color:red; font-weight:bold;'>🔴 {len(section)} Violations</p>"
            html += "<table><tr><th>Course A</th><th>Section A</th><th>Course B</th><th>Section B</th><th>Day(s)</th><th>Time</th></tr>"
            for _, row in section.iterrows():
                html += f"<tr class='{row['RowClass']}'><td>{row['Course A']}</td><td>{row['Section A']}</td><td>{row['Course B']}</td><td>{row['Section B']}</td><td>{row['Day(s)']}</td><td>{row['Time']}</td></tr>"
            html += "</table>"
        else:
            html += "<p>No clashes detected for this pair.</p>"

    # 🔴 CSEE 480S / 481S vs All Departments (300-400)
    html += "<h2>CSEE (480S/481S) - All Departments Clashes (300-400)</h2>"
    if special_csee_clashes:
        html += f"<p style='color:red; font-weight:bold;'>🔴 {len(special_csee_clashes)} Violations</p>"
        html += "<table><tr><th>Course A</th><th>Section A</th><th>Course B</th><th>Section B</th><th>Day(s)</th><th>Time</th></tr>"
        for row in special_csee_clashes:
            html += f"<tr class='{row['RowClass']}'><td>{row['Course A']}</td><td>{row['Section A']}</td><td>{row['Course B']}</td><td>{row['Section B']}</td><td>{row['Day(s)']}</td><td>{row['Time']}</td></tr>"
        html += "</table>"
    else:
        html += "<p>No such clashes found.</p>"

    html += "</body></html>"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path, {
        "CSEE_480S_481S": len(special_csee_clashes),
        "CS-EE": len(grouped[grouped["DeptPair"] == ("CS", "EE")]),
        "EE-CPE": len(grouped[grouped["DeptPair"] == ("EE", "CPE")]),
        "CS-CPE": len(grouped[grouped["DeptPair"] == ("CS", "CPE")])
    }


# --------------------------
# Streamlit App UI
# --------------------------
st.image("logo.png", width=150)
st.title("CourseSync")
st.markdown("##### LCSEE - West Virginia University")
st.markdown("<br>", unsafe_allow_html=True)

instructions_tab, notes_tab, rules_tab = st.tabs(["📂 User Instructions", "📝 Notes", "📏 Rules"])

with instructions_tab:
    st.markdown("### 📂 User Instructions")
    st.markdown("""
    - Upload file in Excel or CSV format and click on the 'Process Schedule' button
    - Uploaded file must include the following columns: Course, Section #, Course Title, Meeting Pattern
    - Once generated, download and open clash reports on a browser
    """)

with notes_tab:
    st.markdown("### 📝 Notes")
    st.markdown("""
    - Only courses that follow standard meeting patterns (day, time) are included
    - Red marked clashes are important
    - Green marked clashes are acceptable
    - In clash report, free slots shown are 1 hour each, from 9 AM to 9 PM on weekdays
    - Wednesday 4-5 PM slots are not shown as available
    """)

with rules_tab:
    st.markdown("### 📏 Rules")
    st.markdown("""
    Important Clash Identification Rules (Red): 
    - Same level courses within departments (300 and above levels)
    - Between 300-400, 500-600, 600-700 level courses within departments
    - Courses scheduled on Wedensday at 4-5 PM
    - Cross department (CS-EE-CPE) same level courses (300 and above levels)
    - Clash between CSEE 480S/481S with any courses from other departments
    """)

st.markdown("---")
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
    # Generate reports
    clash_path, clash_counts = generate_clash_report(df)
    cross_path, cross_counts = generate_cross_dept_clash_report(df)
    # 🔢 Count red clashes from main report
    from bs4 import BeautifulSoup
    main_red_count = 0
    wednesday_count = 0

    with open(clash_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")
        main_red_count = len(soup.find_all("tr", class_="red-row"))

        # Count just Wednesday 4–5PM section
        wed_header = soup.find("h3", string=lambda s: s and "Wednesday 4:00–5:00 PM" in s)
        if wed_header:
            table = wed_header.find_next("table")
            if table:
                wednesday_count = len(table.find_all("tr")) - 1  # exclude header row

    # 🔢 Count red clashes from cross-department report
    cross_red_count = {
        "CSEE 480": 0,
        "CS-EE": 0,
        "EE-CPE": 0,
        "CS-CPE": 0
    }

    with open(cross_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

        # CSEE 480/481
        csee_header = soup.find("h2", string=lambda s: s and "CSEE 480S / 481S" in s)
        if csee_header:
            table = csee_header.find_next("table")
            if table:
                cross_red_count["CSEE 480"] = len(table.find_all("tr")) - 1

        # CS-EE, EE-CPE, CS-CPE
        for label in ["CS – EE", "EE – CPE", "CS – CPE"]:
            sec = soup.find("h2", string=lambda s: s and label in s)
            if sec:
                table = sec.find_next("table")
                if table:
                    count = len(table.find_all("tr")) - 1
                    if "CS – EE" in label:
                        cross_red_count["CS-EE"] = count
                    elif "EE – CPE" in label:
                        cross_red_count["EE-CPE"] = count
                    elif "CS – CPE" in label:
                        cross_red_count["CS-CPE"] = count

    st.session_state.generated = True
    st.success("Clash Report and Calendar Generated!")
    st.markdown("---")
    # ✅ Display summary in Streamlit
    st.markdown("#### 🔴 Clash Summary:")
    st.markdown(f"- Department Wise Clashes: **{clash_counts['non_acceptable']}**")
    st.markdown(f"- Wednesday 4–5 PM Clashes: **{clash_counts['wednesday_4_5']}**")
    st.markdown(f"- CSEE (480S/481S) with All Department (300–400) Clashes: **{cross_counts['CSEE_480S_481S']}**")
    st.markdown(f"- CS – EE Clashes (Same Level): **{cross_counts['CS-EE']}**")
    st.markdown(f"- EE – CPE Clashes (Same Level): **{cross_counts['EE-CPE']}**")
    st.markdown(f"- CS – CPE Clashes (Same Level): **{cross_counts['CS-CPE']}**")
 
  
    # Store file contents in session state to persist after rerun
    if clash_path:
        with open(clash_path, "rb") as f:
            st.session_state.clash_file = f.read()

    if cross_path:
        with open(cross_path, "rb") as f:
            st.session_state.cross_file = f.read()



# Render download buttons after rerun


if st.session_state.get("generated"):
    if "clash_file" in st.session_state:
        st.download_button("📑 Download Department Wise Clash Report", data=st.session_state.clash_file, file_name="clash_report.html", mime="text/html")

    if "cross_file" in st.session_state:
        st.download_button("📑 Download Cross Department Clash Report (CS-EE-CPE-CSEE)", data=st.session_state.cross_file, file_name="cross_report.html", mime="text/html")





# 🗓️ Display Actual-Time Department Calendars



if uploaded and st.session_state.get("generated", False):
    st.markdown("---")
    st.markdown("#### 🗓️ Department Wise Course Calendar")
    dept_calendars = generate_department_calendar_actual_timing(df)
    if dept_calendars:
        tabs = st.tabs([f"📘 {dept}" for dept in dept_calendars.keys()])

        for tab, (dept, table) in zip(tabs, dept_calendars.items()):
            with tab:
                st.markdown(
                    """
                    <style>
                    .styled-table {
                        border-collapse: collapse;
                        margin: 20px 0;
                        font-size: 14px;
                        width: 100%;
                        border: 1px solid #ccc;
                    }
                    .styled-table thead tr {
                        background-color: #004B87;
                        color: #ffffff;
                        text-align: center;
                    }
                    .styled-table th, .styled-table td {
                        padding: 8px 10px;
                        text-align: center;
                        border: 1px solid #ccc;
                        vertical-align: top;
                    }
                    </style>
                    """,
                    unsafe_allow_html=True,
                )

                styled_html = table.fillna("").to_html(
                    escape=False,
                    index=True,
                    classes="styled-table"
                )
                st.markdown(styled_html, unsafe_allow_html=True)

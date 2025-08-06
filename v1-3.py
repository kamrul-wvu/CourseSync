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
    """</div></div>"""

# Elective courses by department
ELECTIVE_COURSES = {
    "CPE": {"CPE 453","CPE 520","CPE 521","CPE 536","CPE 538","CPE 664","CPE 684"},
    "CS": {"CS 450","CS 533","CS 539","CS 555","CS 556","CS 558","CS 568",
           "CS 572","CS 665","CS 674","CS 676","CS 677","CS 678","CS 757"},
    "EE": {"EE 435","EE 436","EE 437","EE 455","EE 461","EE 465",
           "EE 517","EE 528","EE 531","EE 533","EE 535",
           "EE 561","EE 562","EE 565","EE 567","EE 569",
           "EE 613","EE 650","EE 668","EE 713","EE 731","EE 733","EE 735"}
}

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

        for i, row_i in g.iterrows():
            for j, row_j in g.iterrows():
                if i >= j or row_i['Days'] != row_j['Days']:
                    continue
                if time_overlap(row_i['StartTimeObj'], row_i['EndTimeObj'],
                                row_j['StartTimeObj'], row_j['EndTimeObj']):
                    try:
                        level_i = extract_course_level(row_i['Course'])
                        level_j = extract_course_level(row_j['Course'])
                        if level_i is None or level_j is None:
                            continue
                        level_group_i = get_course_level(level_i)
                        level_group_j = get_course_level(level_j)
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
                    except:
                        continue

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

    for dept in df_calendar['Department'].unique():
        html += f"<h2>{dept} Department</h2>"

        dept_group = grouped[grouped['Department'] == dept]

        html += "<h3>📆 Weekly Free Slot Overview (1-Hour Blocks)</h3>"
        html += "<table style='text-align:center; border-collapse:collapse;'><tr><th style='border:1px solid #aaa;'>Time</th>"
        html += "".join(f"<th style='border:1px solid #aaa;'>{day}</th>" for day in days_order)
        html += "</tr>"

        # Generate 1-hour blocks from 9:00 AM to 8:00 PM (last block ends at 9:00 PM)
        hour_slots = []
        t = time(9, 0)
        while (t.hour * 60 + t.minute) <= (20 * 60):  # includes 8:00 PM slot
            end_minutes = (t.hour * 60 + t.minute) + 60
            end_hour, end_min = divmod(end_minutes, 60)
            end = time(end_hour, end_min)
            hour_slots.append((t, end))
            t = end

        # Fill calendar table
        for s, e in hour_slots:
            html += f"<tr><td style='border:1px solid #aaa;'>{s.strftime('%I:%M %p')}–{e.strftime('%I:%M %p')}</td>"
            for day in days_order:
                slot_found = any(
                    (fs <= s and fe >= e) or
                    (
                    s == time(20, 0) and  # 8:00 PM slot
                    (fe.hour * 60 + fe.minute) - (fs.hour * 60 + fs.minute) >= 50 and
                    fs <= s and fe >= s  # partially overlaps starting from 8:00 PM
                    )
                    for fs, fe in free_slots_by_dept[dept][day]
                )

                html += f"<td style='border:1px solid #aaa; color:{'green' if slot_found else '#bbb'};'>{'✅' if slot_found else '—'}</td>"
            html += "</tr>"

        html += "</table>"

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
# HTML Generator for Calendars & Suggested Schedules
# --------------------------
def generate_html_site(df_calendar, output_path, rules=[]):
    os.makedirs(output_path, exist_ok=True)

    df['StartTimeObj'] = df['Start Time'].apply(to_datetime_time_safe)
    df['EndTimeObj'] = df['End Time'].apply(to_datetime_time_safe)
    df_calendar['Level Color'] = df_calendar['Course Level'].map(level_colors)
    df_calendar.dropna(subset=['StartTimeObj', 'EndTimeObj'], inplace=True)

    dept_files = {}
    # generate individual dept calendars
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

        # existing elective-dept rule
        if st.session_state.get("elective_depts"):
            for ed in st.session_state.elective_depts:
                for i, row_i in g.iterrows():
                    for j, row_j in g.iterrows():
                        if i >= j or row_i['Days'] != row_j['Days']:
                            continue
                        course_i = f"{row_i['Department']} {int(row_i['Course Number'])}"
                        course_j = f"{row_j['Department']} {int(row_j['Course Number'])}"
                        if row_i['Department']==ed and row_j['Department']==ed and course_i in ELECTIVE_COURSES[ed] and course_j in ELECTIVE_COURSES[ed]:
                            g.at[i, 'Clash'] = True
                            g.at[j, 'Clash'] = True
                            g.at[i, 'Clash Details'] += f"Violates elective-dept rule with {course_j}; "
                            g.at[j, 'Clash Details'] += f"Violates elective-dept rule with {course_i}; "

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
                html += f"{row['Course']} - {row['Course Title']} <br> Level: ({row['Course Level']})<br>Section: {row['Section #']}" 
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
        <html><head><title>Suggested Optimal Schedules</title><style>
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
        """
        )

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
                        # existing level-based rule
                        if violates_custom_rule(row_i, row_j, rules):
                            conflict = True
                            break
                        # existing non-clash-pairs rule
                        for pair in st.session_state.get("non_clash_pairs", []):
                            course_i = f"{row_i['Department']} {int(row_i['Course Number'])}"
                            course_j = f"{row_j['Department']} {int(row_j['Course Number'])}"
                            if (course_i, course_j) in [pair, pair[::-1]]:
                                conflict = True
                                break
                        if conflict:
                            break
                        # elective-dept rule
                        for ed in st.session_state.get("elective_depts", []):
                            ci = f"{row_i['Department']} {int(row_i['Course Number'])}"
                            cj = f"{row_j['Department']} {int(row_j['Course Number'])}"
                            if (row_i['Department']==ed and row_j['Department']==ed and
                                ci in ELECTIVE_COURSES[ed] and cj in ELECTIVE_COURSES[ed]):
                                conflict = True
                                break
                        if conflict:
                            break
                        # cross-department elective rule
                        for d1, d2 in st.session_state.get("cross_elective_pairs", []):
                            ci = f"{row_i['Department']} {int(row_i['Course Number'])}"
                            cj = f"{row_j['Department']} {int(row_j['Course Number'])}"
                            if ((row_i['Department'], row_j['Department']) == (d1, d2) or (row_i['Department'], row_j['Department']) == (d2, d1)):
                                if ci in ELECTIVE_COURSES.get(row_i['Department'], []) and cj in ELECTIVE_COURSES.get(row_j['Department'], []):
                                    conflict = True
                                    break
                        if conflict:
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
        f.write("""<!DOCTYPE html><html><head><title>WVU Department Calendars</title><style>
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
        <div class='section-title'>Based on the uploaded file</div><div class='grid'>"""
        )
        for dept, fname in dept_files.items():
            f.write(f'<a class="card" href="{fname}" target="_blank">{dept}</a>')
#        f.write("""</div><div class='section-title'>Suggested</div>
#        <div class='grid'><a class='card' href='suggested_schedules.html' target='_blank'>Optimal Schedule</a></div>
#        </body></html>"""
#        )

    return os.path.abspath(os.path.join(output_path, "calendar_directory.html"))

# --------------------------
# Streamlit App UI
# --------------------------
st.image("logo.png", width=150)
st.title("CourseSync")
st.markdown("##### Course Calendar Generator")
st.markdown("##### West Virginia University")
st.markdown("<br>", unsafe_allow_html=True)
uploaded = st.file_uploader("Upload Excel file: Must include the following columns: Course, Section #, Course Title, Meeting Pattern, room", type=['xlsx'])
if uploaded:
    df = pd.read_excel(uploaded)
    df[['Days', 'Start Time', 'End Time']] = df['Meeting Pattern'].apply(parse_meeting_pattern)
    df['Course Number'] = df['Course'].str.extract(r'(\d{3})').astype(float)
    df['Department'] = df['Course'].str.extract(r'^([A-Z]+)')
    df['Course Level'] = df['Course Number'].apply(get_course_level)
    df = df[df['Course Level'] != 'Unknown']
    df.reset_index(drop=True, inplace=True)


if st.button(":gear: Process Schedule"):
    site_path = generate_html_site(df, "calendar_site", st.session_state.rule_list)
    clash_path = generate_clash_report(df)

    # Save the URLs in session state so buttons remain after rerun
    st.session_state.calendar_url = "file://" + os.path.abspath(os.path.join("calendar_site", "calendar_directory.html"))
    st.session_state.clash_url = "file://" + os.path.abspath(clash_path)
    st.session_state.generated = True  # flag to show buttons

    st.success("Calendar and Clash Report generated!")

# Show buttons if already generated
if st.session_state.get("generated", False):
    if st.button(":calendar: Open Calendar Directory"):
        webbrowser.open_new_tab(st.session_state.calendar_url)

    if st.button(":receipt: Open Clash Report"):
        webbrowser.open_new_tab(st.session_state.clash_url)


st.markdown("<br>", unsafe_allow_html=True)

st.markdown("###### Optional Rules for Scheduling:")

# Rule 01: Prevent overlapping same‐hundreds‐level courses in one dept
st.markdown("**Rule 01:** Courses of the same level within a department should not overlap")
with st.form("rule_form"):
    col1, col2 = st.columns(2)
    with col1:
        d1 = st.text_input("Department", placeholder="CS, EE, CPE")
    with col2:
        l1 = st.selectbox("Level (hundreds)", [100,200,300,400,500,600,700])
    add1 = st.form_submit_button("➕ Add Level Rule")

st.session_state.setdefault("rule_list", [])
if add1 and d1 and l1:
    st.session_state.rule_list.append((d1.upper(), l1))
if st.session_state.rule_list:
    st.markdown("**Active Level Rules:**")
    for i,(dep,lev) in enumerate(st.session_state.rule_list):
        cols=st.columns([8,1])
        with cols[0]:
            st.write(f"• No {dep} {lev}-level overlap")
        with cols[1]:
            if st.button("🗑️", key=f"rm1_{i}"):
                st.session_state.rule_list.pop(i); st.rerun()

# Rule 02: Specific course pairs must not clash
st.markdown("**Rule 02:** These specific course pairs must not overlap")
with st.form("non_clash_form"):
    ca = st.text_input("Course A", placeholder="e.g. CS 330")
    cb = st.text_input("Course B", placeholder="e.g. CS 230")
    add2 = st.form_submit_button("➕ Add Pair")

st.session_state.setdefault("non_clash_pairs", [])
if add2 and ca and cb:
    st.session_state.non_clash_pairs.append((ca.upper(), cb.upper()))
if st.session_state.non_clash_pairs:
    st.markdown("**Active Pairs:**")
    for i,(a,b) in enumerate(st.session_state.non_clash_pairs):
        cols=st.columns([8,1])
        with cols[0]:
            st.write(f"• {a} should not overlap with {b}")
        with cols[1]:
            if st.button("🗑️", key=f"rm2_{i}"):
                st.session_state.non_clash_pairs.pop(i); st.rerun()

# Rule 03: Electives within one dept must not clash
st.markdown("**Rule 03:** No two electives in the same department should overlap")
with st.form("elective_dept_form"):
    d3 = st.selectbox("Department", ["CPE","CS","EE"])
    add3 = st.form_submit_button("➕ Add Elective-Dept Rule")

st.session_state.setdefault("elective_depts", [])
if add3:
    st.session_state.elective_depts.append(d3)
if st.session_state.elective_depts:
    st.markdown("**Active Elective-Dept Rules:**")
    for i,dep in enumerate(st.session_state.elective_depts):
        cols=st.columns([8,1])
        with cols[0]:
            st.write(f"• Electives in {dep} should not overlap")
        with cols[1]:
            if st.button("🗑️", key=f"rm3_{i}"):
                st.session_state.elective_depts.pop(i); st.rerun()

# Rule 04: Electives across two depts must not clash
st.markdown("**Rule 04:** Electives in these departments must not overlap")
with st.form("cross_elective_form"):
    d4a = st.selectbox("Department A", ["CPE","CS","EE"], key="d4a")
    d4b = st.selectbox("Department B", ["CPE","CS","EE"], key="d4b")
    add4 = st.form_submit_button("➕ Add Cross-Elective Rule")

st.session_state.setdefault("cross_elective_pairs", [])
if add4 and d4a and d4b and d4a!=d4b:
    pair = tuple(sorted((d4a, d4b)))
    if pair not in st.session_state.cross_elective_pairs:
        st.session_state.cross_elective_pairs.append(pair)
if st.session_state.cross_elective_pairs:
    st.markdown("**Active Cross-Elective Rules:**")
    for i,(x,y) in enumerate(st.session_state.cross_elective_pairs):
        cols=st.columns([8,1])
        with cols[0]:
            st.write(f"• Electives in {x} should not clash with electives in {y}")
        with cols[1]:
            if st.button("🗑️", key=f"rm4_{i}"):
                st.session_state.cross_elective_pairs.pop(i); st.rerun()

st.markdown("<br>", unsafe_allow_html=True)
st.markdown("""
    <div style="position: center; bottom: 0; width: 100%; text-align: center; padding: 10px;">
        <p style="font-size: 12px; color: #FFF;">Queries: kamrul.hasan@mail.wvu.edu</p>
	<p style="font-size: 12px; color: #FFF;">Version: 1.3</p>
    </div>
    """, unsafe_allow_html=True)
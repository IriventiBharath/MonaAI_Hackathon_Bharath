import os
import re
import sqlite3
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

EXCEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hospital_schedule_part_2.xlsx")

DATE_COLUMNS = {
    "Fri 06/19": "fri_0619",
    "Sat 06/20": "sat_0620",
    "Sun 06/21": "sun_0621",
    "Mon 06/22": "mon_0622",
    "Tue 06/23": "tue_0623",
    "Wed 06/24": "wed_0624",
    "Thu 06/25": "thu_0625",
    "Fri 06/26": "fri_0626",
}

PREV_DAY_COL = {
    "fri_0619": None,
    "sat_0620": "fri_0619",
    "sun_0621": "sat_0620",
    "mon_0622": "sun_0621",
    "tue_0623": "mon_0622",
    "wed_0624": "tue_0623",
    "thu_0625": "wed_0624",
    "fri_0626": "thu_0625",
}

SHIFT_OPTIONS = {
    "N - Night (19:00-07:00)": "N",
    "D - Day (07:00-19:00)": "D",
}


def sanitize_col(col: str) -> str:
    col = str(col).strip().lower()
    col = re.sub(r"[^a-z0-9]+", "_", col)
    return col.strip("_")


@st.cache_data
def load_data():
    xl = pd.ExcelFile(EXCEL_PATH)
    roster = pd.read_excel(xl, sheet_name="Roster")
    schedule = pd.read_excel(xl, sheet_name="Weekly_Schedule")
    # Normalise all column headers to plain strings
    roster.columns = [str(c).strip() for c in roster.columns]
    schedule.columns = [str(c).strip() for c in schedule.columns]
    return roster, schedule


@st.cache_resource
def build_db(_roster_df, _schedule_df):
    """Load DataFrames into an in-memory SQLite database."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)

    # ── Roster table ──────────────────────────────────────────────────────────
    r = _roster_df.copy()
    r.columns = [sanitize_col(c) for c in r.columns]
    if "first_name" in r.columns and "last_name" in r.columns:
        r["full_name"] = (r["first_name"].fillna("") + " " + r["last_name"].fillna("")).str.strip()
    r.to_sql("roster", conn, if_exists="replace", index=False)

    # ── Weekly schedule table ─────────────────────────────────────────────────
    s = _schedule_df.copy()
    new_cols = []
    for col in s.columns:
        col_str = str(col).strip()
        if col_str in DATE_COLUMNS:
            new_cols.append(DATE_COLUMNS[col_str])
        elif re.search(r"scheduled\s*hrs", col_str, re.I):
            new_cols.append("scheduled_hrs")
        else:
            new_cols.append(sanitize_col(col_str))
    s.columns = new_cols
    s.to_sql("weekly_schedule", conn, if_exists="replace", index=False)

    return conn


def get_person_details(selected_name: str, roster_df, schedule_df) -> dict:
    row = schedule_df[schedule_df["Name"] == selected_name]
    if row.empty:
        return {}
    emp_id = row.iloc[0]["Employee ID"]
    rrow = roster_df[roster_df["Employee ID"] == emp_id]
    if rrow.empty:
        return {}
    r = rrow.iloc[0]
    return {
        "employee_id": str(emp_id),
        "name": selected_name,
        "role": str(r.get("Role", "")),
        "department": str(r.get("Department", "")),
        "certifications": str(r.get("Certifications", "")),
    }


def generate_sql(api_key: str, missing: dict, date_col: str, shift_code: str, prev_col) -> str:
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")

    certs_raw = missing.get("certifications", "")
    certs = [c.strip() for c in re.split(r"[/,]", certs_raw) if c.strip()]
    cert_sql = (
        " AND ".join([f"r.certifications LIKE '%{c}%'" for c in certs])
        if certs
        else "1=1"
    )

    shift_label = "Night (19:00–07:00)" if shift_code == "N" else "Day (07:00–19:00)"

    rest_note = ""
    if shift_code == "D" and prev_col:
        rest_note = (
            f"\n8. Rest check (Day shift): ws.{prev_col} != 'N'  "
            f"-- exclude staff who just finished a Night shift ending at 07:00 this morning"
        )

    prompt = f"""You are a hospital scheduling assistant. Write ONE SQLite SELECT query to find valid shift replacement candidates. Output ONLY raw SQL — no markdown, no backticks, no explanation.

SCHEMA
------
TABLE roster
  Columns: employee_id, first_name, last_name, full_name, role, department,
           certifications, contract, max_hrs_week, overtime_ok, status,
           persona_notes, last_clock_out, phone

TABLE weekly_schedule
  Columns: employee_id, name, role, department,
           fri_0619, sat_0620, sun_0621, mon_0622, tue_0623, wed_0624, thu_0625, fri_0626,
           scheduled_hrs

Shift codes in schedule columns: 'D' = Day 07:00-19:00 (12 h), 'N' = Night 19:00-07:00 (12 h), 'O' = Off

MISSING PERSON
--------------
employee_id : {missing['employee_id']}
role        : {missing['role']}
department  : {missing['department']}
certifications needed: {missing['certifications']}

TARGET SHIFT: {shift_label} — date column: ws.{date_col}

ELIGIBILITY — ALL conditions required
--------------------------------------
1.  r.status = 'Active'
2.  Role match:  r.role = '{missing['role']}'
    OR ('{missing['role']}' IN ('Registered Nurse','Charge Nurse')
        AND r.role IN ('Registered Nurse','Charge Nurse'))
3.  r.department = '{missing['department']}'
4.  Certifications: {cert_sql}
5.  Off on target day: ws.{date_col} = 'O'
6.  Hours cap: (CAST(r.max_hrs_week AS REAL) - CAST(ws.scheduled_hrs AS REAL)) >= 12
7.  Not the absent person: r.employee_id != '{missing['employee_id']}'{rest_note}

JOIN
----
roster r INNER JOIN weekly_schedule ws ON r.employee_id = ws.employee_id

SELECT
------
r.employee_id,
r.full_name,
r.role,
r.department,
r.certifications,
r.contract,
r.max_hrs_week,
r.overtime_ok,
r.phone,
ws.scheduled_hrs,
(CAST(r.max_hrs_week AS REAL) - CAST(ws.scheduled_hrs AS REAL)) AS hours_headroom,
r.persona_notes,
r.last_clock_out

ORDER BY
--------
CASE WHEN r.overtime_ok = 'Yes' THEN 0 ELSE 1 END ASC,
hours_headroom DESC,
CASE r.contract WHEN 'Per-diem' THEN 0 WHEN 'Part-time' THEN 1 ELSE 2 END ASC"""

    response = model.generate_content(prompt)
    sql = response.text.strip()
    # Strip any accidental markdown fences
    sql = re.sub(r"^```[a-z]*\s*", "", sql, flags=re.MULTILINE | re.IGNORECASE)
    sql = re.sub(r"```\s*$", "", sql, flags=re.MULTILINE)
    return sql.strip()


def execute_sql(conn, sql: str):
    try:
        return pd.read_sql_query(sql, conn), None
    except Exception as exc:
        return None, str(exc)


def draft_outreach(api_key: str, cand_name: str, role: str, dept: str, shift_label: str, date_display: str) -> str:
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    first = cand_name.split()[0]
    prompt = (
        f"Write a 2-sentence urgent but warm hospital HR SMS to {cand_name} asking them to cover a shift.\n"
        f"Role: {role}, Department: {dept}\n"
        f"Shift: {shift_label} on {date_display}\n"
        f"Start with 'Hi {first},' — no sign-off. Stay under 200 characters total."
    )
    response = model.generate_content(prompt)
    return response.text.strip()


# ── Streamlit UI ──────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Shift Replacement Agent",
        page_icon="🏥",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(
        """
        <h1 style='margin-bottom:0'>🏥 Shift Replacement Agent</h1>
        <p style='color:grey;margin-top:4px'>
        Fill last-minute shift gaps — Gemini generates the query, you make the call.
        </p>
        """,
        unsafe_allow_html=True,
    )
    st.divider()

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        st.error("GEMINI_API_KEY not found in .env file.")
        st.stop()

    roster_df, schedule_df = load_data()
    conn = build_db(roster_df, schedule_df)

    all_names = sorted(schedule_df["Name"].dropna().unique().tolist())
    all_roles = sorted(roster_df["Role"].dropna().unique().tolist())
    all_depts = sorted(roster_df["Department"].dropna().unique().tolist())

    # ── Sidebar inputs ────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("📋 Shift Details")
        st.caption("Select who is missing and what needs to be covered.")

        selected_name = st.selectbox("Missing Staff Member", all_names)
        person = get_person_details(selected_name, roster_df, schedule_df)

        auto_role = person.get("role", all_roles[0])
        auto_dept = person.get("department", all_depts[0])
        role_idx = all_roles.index(auto_role) if auto_role in all_roles else 0
        dept_idx = all_depts.index(auto_dept) if auto_dept in all_depts else 0

        role = st.selectbox("Role", all_roles, index=role_idx)
        dept = st.selectbox("Department", all_depts, index=dept_idx)
        date_display = st.selectbox("Date Needing Coverage", list(DATE_COLUMNS.keys()), index=1)
        shift_display = st.selectbox("Shift to Cover", list(SHIFT_OPTIONS.keys()))

        st.divider()
        find_clicked = st.button("🔍 Find Replacement", type="primary", use_container_width=True)

        st.divider()
        if person:
            st.markdown("**Selected staff info**")
            st.markdown(f"- **ID:** `{person.get('employee_id', '—')}`")
            st.markdown(f"- **Role:** {person.get('role', '—')}")
            st.markdown(f"- **Dept:** {person.get('department', '—')}")
            st.markdown(f"- **Certs:** {person.get('certifications', '—')}")

    # ── Main area ─────────────────────────────────────────────────────────────
    if "results_data" not in st.session_state:
        st.session_state.results_data = None

    if find_clicked:
        if not person.get("employee_id"):
            st.error("Could not resolve employee details. Please pick a valid name.")
            st.stop()

        person["role"] = role
        person["department"] = dept
        shift_code = SHIFT_OPTIONS[shift_display]
        date_col = DATE_COLUMNS[date_display]
        prev_col = PREV_DAY_COL[date_col]

        with st.status("Finding eligible replacements…", expanded=True) as status:
            st.write("⚙️ Asking Gemini to write the SQL query…")
            try:
                sql = generate_sql(api_key, person, date_col, shift_code, prev_col)
            except Exception as exc:
                status.update(label="Gemini error", state="error")
                st.error(f"Gemini SQL generation failed: {exc}")
                st.stop()

            st.write("🗄️ Executing query against schedule database…")
            results, err = execute_sql(conn, sql)

            if err:
                status.update(label="SQL execution error", state="error")
                st.error(f"SQL error: {err}")
                st.code(sql, language="sql")
                st.stop()

            if results is None or results.empty:
                status.update(label="No eligible candidates found", state="complete")
                st.session_state.results_data = {
                    "results": pd.DataFrame(),
                    "sql": sql,
                    "messages": {},
                    "context": {
                        "person": person,
                        "shift": shift_display,
                        "date": date_display,
                    },
                }
            else:
                st.write(f"✅ Found **{len(results)}** candidate(s). Drafting outreach messages…")
                messages = {}
                for _, row in results.iterrows():
                    try:
                        msg = draft_outreach(
                            api_key,
                            row["full_name"],
                            row["role"],
                            row["department"],
                            shift_display,
                            date_display,
                        )
                    except Exception:
                        msg = "Could not generate message."
                    messages[row["employee_id"]] = msg

                status.update(label=f"Done — {len(results)} replacement(s) found", state="complete")
                st.session_state.results_data = {
                    "results": results,
                    "sql": sql,
                    "messages": messages,
                    "context": {
                        "person": person,
                        "shift": shift_display,
                        "date": date_display,
                    },
                }

    # ── Display stored results ────────────────────────────────────────────────
    if st.session_state.results_data is not None:
        data = st.session_state.results_data
        results: pd.DataFrame = data["results"]
        sql: str = data["sql"]
        messages: dict = data["messages"]
        ctx: dict = data["context"]
        p = ctx["person"]

        col1, col2 = st.columns([3, 1])
        with col1:
            st.subheader(
                f"Replacement candidates for {p['name']} — {ctx['shift']} on {ctx['date']}"
            )
        with col2:
            with st.expander("🔍 Generated SQL"):
                st.code(sql, language="sql")

        if results.empty:
            st.warning("No eligible staff found who match all criteria for this shift.")
        else:
            # ── Summary table ─────────────────────────────────────────────────
            display_map = {
                "full_name": "Name",
                "role": "Role",
                "department": "Dept",
                "certifications": "Certifications",
                "contract": "Contract",
                "overtime_ok": "OT OK",
                "hours_headroom": "Hrs Available",
                "phone": "Phone",
            }
            display_cols = [c for c in display_map if c in results.columns]
            styled = results[display_cols].rename(columns=display_map).reset_index(drop=True)
            styled.index += 1
            st.dataframe(styled, use_container_width=True)

            st.divider()
            st.subheader("📱 Outreach Messages")
            st.caption("Ready-to-send drafts — review and call or text each candidate.")

            for rank, (_, row) in enumerate(results.iterrows(), start=1):
                emp_id = row["employee_id"]
                cand_name = row.get("full_name", "Staff")
                phone = row.get("phone", "N/A")
                ot_ok = row.get("overtime_ok", "No")
                hrs = row.get("hours_headroom", 0)
                contract = row.get("contract", "")
                certs = row.get("certifications", "")

                badge = "🟢" if ot_ok == "Yes" else "🟡"
                label = (
                    f"#{rank}  {badge}  **{cand_name}** — {phone}  "
                    f"|  OT: {ot_ok}  |  {hrs:.0f} h available  |  {contract}"
                )

                with st.expander(label, expanded=(rank == 1)):
                    c_left, c_right = st.columns([1.4, 1])

                    with c_left:
                        st.markdown("**Draft SMS**")
                        msg = messages.get(emp_id, "Message unavailable.")
                        st.info(msg)
                        st.caption(f"📞 {phone}")

                    with c_right:
                        st.markdown("**Candidate profile**")
                        st.markdown(f"- **Certifications:** {certs}")
                        st.markdown(f"- **Contract:** {contract}")
                        st.markdown(f"- **Overtime OK:** {ot_ok}")
                        st.markdown(f"- **Hours available:** {hrs:.0f} h")
                        notes = row.get("persona_notes", "")
                        if notes and str(notes) != "nan":
                            st.markdown(f"- **Notes:** {notes}")
                        last_out = row.get("last_clock_out", "")
                        if last_out and str(last_out) != "nan":
                            st.markdown(f"- **Last clock-out:** {last_out}")

    elif not find_clicked:
        st.info("Select the missing staff member and shift details in the sidebar, then click **Find Replacement**.")


if __name__ == "__main__":
    main()

# GoalTracker — Analytics-First Time & Sprint Performance Tracker (Django + Power BI)

GoalTracker is an **analytics-first time tracking system** built to measure daily work quality and sprint momentum. It captures sessions with **quality weighting** (“effective minutes”), rolls them into **daily/sprint KPIs**, and supports **Power BI reporting** with a clean, interview-ready narrative (Hiring Manager Summary).

---

## Why this project matters (for Data roles)

Most trackers record hours. GoalTracker answers the questions hiring managers care about:

- How much work was **effective**, not just logged?
- Are you sustaining **sprint pace** over 7/14/30 days?
- Where is time concentrated (goal/category/work item)?
- Can you define metrics clearly and make them reproducible in BI?

This project demonstrates **Data Analyst / Analytics Engineer** skills: metric design, data modeling concepts, and report-driven storytelling.

---

## Core features

### Tracking workflow
- **Active Day** lifecycle: Start Day → track work → End Day reflection  
  Includes `wake_at`, `sleep_at`, `is_open` for auditability.
- **Active Timer** (one per active goal)
  - category
  - quality level
  - deliverable (required for “Exceptional”)
  - accumulated minutes + live running segment
- **Sessions** (immutable log)
  - start/end timestamps
  - duration minutes
  - quality level + multiplier
  - **effective minutes**
  - MAE block (Morning/Afternoon/Evening)
  - deliverable + notes
  - optional linkage to **WorkItem** (delivery-focused tracking)

### Taxonomy & slicing
- Categories (Admin/Planning, Deep Work, Interview Prep, etc.)
- Optional **WorkItem** support for deliverable-level tracking
- Tagging model:
  - `TagGroup`, `Tag`, `SessionTag` (many-to-many sessions tagging)

### Reporting
- Trend: **Raw vs Effective** over time
- Daily breakdown cards (paged)
- Sprint window selector: **7 / 14 / 30** days
- **Hiring Manager Summary** page: KPI cards + short narrative

---

## Metric definitions

### Total Minutes (Raw)
Actual logged minutes between `start_at` and `end_at`.

### Effective Minutes (Weighted)
Quality-weighted score:

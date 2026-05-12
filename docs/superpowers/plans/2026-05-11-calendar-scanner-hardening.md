# Calendar Scanner Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Claude's local Calendar Scanner safer to evolve by aligning docs with GitHub references, fixing strategy fetch behavior, adding TimeZone rule flags, and adding strategy presets.

**Architecture:** Keep the scanner modular: strategy modules own structure-specific rules, the registry owns dispatch/defaults, and scoring presets live in a small shared helper. Do not import or modify `batman-scanner`; borrow only simple patterns that fit this repo.

**Tech Stack:** Python 3.13, Streamlit, `unittest`, `ib_insync`, SQLite cache.

---

### Task 1: Project Git Boundary

**Files:**
- Modify/create: `.git/` metadata only

- [x] Initialize `Calendar-Scanner` as a standalone Git repo if it is still using `/Users/bhaviksarvaiya` as the root.
- [x] Add `https://github.com/bravo81-hash/Calendar-Scanner.git` as `origin` if absent.
- [x] Do not push or overwrite remote history.

### Task 2: Import New Strategy References

**Files:**
- Create: `docs/strategies_html/A14.html`
- Create: `docs/strategies_html/FlyDiagonal.html`
- Create: `docs/strategies_html/HV7.html`
- Modify: `docs/STRATEGIES.md`
- Modify: `README.md`

- [x] Copy the three new HTML reference files from the GitHub checkout into local docs.
- [x] Add concise summaries explaining that A14/HV7/FlyDiagonal are BWB or diagonal-family references, not yet live builders.
- [x] Update README strategy/reference layout.

### Task 3: Strategy Rights Fetching

**Files:**
- Modify: `strategies/time_edge.py`
- Modify: `strategies/triple_calendar.py`
- Test: `tests/test_strategy_rights.py`

- [x] Write tests proving main TimeEdge requests only puts while No-Touch requests puts and calls.
- [x] Write a test proving Triple Calendar can request calls when full straddle EM is enforced.
- [x] Add a `triple_require_full_straddle` setting defaulting to false.
- [x] Update config/docs for the new setting.

### Task 4: TimeZone Delta-Flat Rule

**Files:**
- Modify: `strategies/time_zone.py`
- Test: `tests/test_strategies_mock.py`

- [x] Write a failing test for the documented TimeZone rule: absolute delta should be flagged when greater than 10% of absolute theta.
- [x] Add extras fields for `delta_flat_limit`, `delta_flat_pass`, and `delta_flat_ratio`.
- [x] Surface a warning when the rule fails, but do not reject the candidate yet.

### Task 5: Per-Strategy Scoring Presets

**Files:**
- Create: `scanner/presets.py`
- Modify: `app.py`
- Test: `tests/test_presets.py`

- [x] Add preset helpers that return conservative default weights per strategy.
- [x] Add a sidebar selector to apply strategy defaults or custom weights.
- [x] Keep existing sliders editable after preset application.

### Task 6: Verification

**Files:**
- Test: all tests

- [x] Run `python3 -m unittest discover -s tests -v`.
- [x] Confirm the Streamlit app still starts.
- [x] Report exact verification output and any remaining risks.

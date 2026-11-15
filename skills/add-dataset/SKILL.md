---
name: add-dataset
description: Add a new dataset to adele. Use when a data analyst wants to add a source to the adele catalog. The analyst writes the definitions by hand; this skill places them in datapackage.yaml, writes fetch.py and runs the checks.
---

# Add a dataset to adele

Revised 2026-11-13 after the first dataset (ENTSO-E day-ahead prices). What changed and why:
the measurements of that day are in `datasets/entsoe_day_ahead_prices/fetch.py` (docstring) and
in `skills/common-traps.md`. Revised 2026-11-15 after the second (ENTSO-E load): step 8, the QA
with published figures.

A dataset is a folder `datasets/<id>/` with `datapackage.yaml`, `fetch.py` and `checks.yaml`
(SPEC.md, "Adding a dataset" and "Catalog").

## Who writes what

The data analyst writes every definition by hand. You do not write, complete or reword a
definition.

Written by the analyst:

- title and description of the dataset
- description and unit of each field
- the grain (which columns identify one row)
- the label of each code value
- the warnings (`adele.warnings`)
- the questions of the example queries, and the check that each answer is right

Done by you:

- ask the questions that the analyst has to answer
- place the analyst's text in `datapackage.yaml` at the right key, word for word
- write `fetch.py`
- collect published figures (from the analyst's own reports first) and write them as checks in
  `checks.yaml`
- measure facts on the data and show them to the analyst (types, distinct values, ranges,
  rows per day). A measured fact is evidence for the analyst. It is not a definition.

If a definition is missing, ask for it. Do not fill the gap. If you think that a definition
is wrong, show the evidence from the data and let the analyst decide.

## Steps

1. **Source.** Ask where the data comes from, how it is published (file, API), how often, and
   under which licence. Fetch a sample. Ask also whether the analyst has reports of their own
   (PDF, Excel) with figures computed from this source: they become the checks of step 8, and
   the analyst may need some time to find them.
2. **Measure.** Measure the raw response of the source, not the output of a client library:
   libraries reshape data silently (resampling, merging series). Profile it (DuckDB
   `SUMMARIZE`, distinct values of text columns, rows per day, duplicates on the candidate
   key) and show the result to the analyst. Measure per series, not per dataset: the
   resolution, the first and last date and the gaps of each zone or code, because they can
   differ. Ask for a long window once and compare the rows received with the rows that the
   window should hold: sources cut long responses without an error.
3. **Traps.** Go through `skills/common-traps.md` with the analyst, one question at a time.
   Each answer becomes either a step of normalization in `fetch.py`, or a sentence written by
   the analyst for a field description or for `adele.warnings`. Prefer normalization: a trap
   that a column removes is better than a trap that a sentence explains.
4. **Definitions.** Collect the analyst's text for each item of the list above. Place it in
   `datapackage.yaml` following the rule "Keys or prose" of SPEC.md.
   The time column of each table gives its shape (SPEC.md, Time conventions; D17, D22, D26):
   `delivery_start` (an interval of fixed length, UTC), `valid_at` (an instant, UTC),
   `delivery_date`, `delivery_month` or `delivery_year` (a calendar period, type date, a month
   or a year stored as its first day), or none (a list of stations, a register: each fetch
   replaces the table whole, and must return it whole). A table by calendar period declares its
   zone in its own `adele:` block (`timezone: Europe/Zurich`, an IANA name or `UTC`, never
   `CET`). When the source does not state the zone of its days, ask the analyst for the most
   likely zone, and the description of the column says that it is assumed. A day of UTC is a
   fixed length: it keeps `delivery_start` with `P1D`. The `adele:` block of a table holds
   `resolution`, `partition` and `timezone`; the package-level `resolution` and `partition`
   apply to the tables that set none. These shapes need `adele.format_version: 2`.
5. **fetch.py.** Write `fetch(start, end)`. Apply the conventions of SPEC.md: UTC, timestamp
   at the start of the interval, half-open intervals, one unit per field, a `resolution`
   column when the resolution differs between series or over time. Put a timeout on every
   network call. Split long windows into requests that the source answers whole, and check
   that each response covers what was asked (if not, split again). Write what you measured in
   the docstring of `fetch.py`, with the date: the next person needs the evidence.
   With `revisions: append-only`, a row that differs from its stored version in any column
   becomes a new version (D30). So `fetch.py` returns no column that changes at each answer
   (the source's creation time of the document, a request id): each fetch would store every
   row again. Get the units and the schema right before the backfill, because adele can't
   convert stored versions later.
   A calendar period is returned as `datetime.date` values (pandas: `.dt.date`), not as
   timestamps. A table without a time column is returned whole at every call, also when the
   window is short: an empty answer is an error.
6. **Example queries.** For each question that the analyst gives, write the SQL, run it, and
   show the result. The analyst confirms the result before the entry gets a `verified_at`.
   Once `checks.yaml` exists (step 8), a check can be an example too (`- check: <name>`): pick
   the checks whose SQL shows a trap that the other examples don't. Five examples at most; `describe` prints
   them all.
7. **Check.** Validate the descriptor (`adele-server validate`), run the fetch on a short
   window, run it again (it must change nothing), then backfill. Profile the stored data:
   gaps per series, days of the clock change (23 and 25 hours), extremes, the first day of
   each change of resolution.
8. **Published figures (the QA).** The QA of a dataset is a list of figures that others
   computed from the same data and published: the stored data must reproduce them (SPEC.md,
   `checks.yaml`; D12). The server runs them after each fetch and on `adele-server check <id>`;
   a value outside its tolerance sets the status to failing. Two models:
   `datasets/entsoe_day_ahead_prices/checks.yaml` (82 figures from ElCom, SMARD, CRE, RTE and
   papers; notes in `qa/published_figures.md`) and `datasets/entsoe_load/checks.yaml` (50
   figures from ENTSO-E's factsheets and two papers; notes in
   `qa/published_figures_entsoe_load.md`).
   - **The analyst's documents first.** Ask the analyst for their own reports, PDF or Excel,
     that hold figures computed from this source: yearly totals or means, extremes with their
     hour, counts of hours. An Excel file is the best case: many figures, exact values, and an
     analyst who can say how each one was computed. For each figure that you take, ask how it
     was computed (the period, local or UTC year, a filter).
   - **Then published reports.** Search for documents that state that they use this source:
     the source's own statistics (e.g. ENTSO-E's factsheets), regulators, system operators,
     statistics offices, exchanges, papers. Prefer figures that test a trap: a count of hours
     with a negative price tests the resolution, an extreme with its hour tests the stamps, a
     yearly total tests the gaps.
   - **Compare.** Compute each figure on the stored data with a script
     `qa/tools/published_check_<id>.py`, and write the result in
     `qa/published_figures_<id>.md`: the sources, the figures that match, and each figure that
     differs with its reason. A figure that differs is a finding: look for the reason (the
     definition, the zone of the year, the stamps, missing days, the rounding) and show it to
     the analyst before you leave the figure out. A difference that you can't explain stays
     in the notes as unexplained.
   - **Write the checks.** Each figure that matches becomes an entry with `name`, `question`,
     `sql` (one row, one number), `expected`, `tolerance` and `source`. The question states
     the zone, the period, and whether the year is local or UTC. The tolerance follows from
     the rounding of the published value (0.5 for whole numbers, 0.05 for one decimal); a
     wider tolerance needs a reason in the comment at the top of the file. The source names
     the document, the table or page, and the URL; for a document of the analyst that is not
     online, the title, the date, the sheet or page, and where the analyst keeps it. The
     comment at the top of the file says when and how the figures were collected, the rule
     for the tolerance and the conventions (which codes, local or UTC years). Run
     `adele-server validate` and `adele-server check <id>`: every check passes.
9. **Review.** Propose to run the skill `review-dataset` before the dataset is published.

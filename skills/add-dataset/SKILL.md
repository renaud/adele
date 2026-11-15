---
name: add-dataset
description: Add a new dataset to adele. Use when a data analyst wants to add a source to the adele catalog. The analyst writes the definitions by hand; this skill places them in datapackage.yaml, writes fetch.py and runs the checks.
---

# Add a dataset to adele

Revised 2026-11-13 after the first dataset (ENTSO-E day-ahead prices). What changed and why:
the measurements of that day are in `datasets/entsoe_day_ahead_prices/fetch.py` (docstring) and
in `skills/common-traps.md`.

A dataset is a folder `datasets/<id>/` with `datapackage.yaml` and `fetch.py` (SPEC.md,
"Adding a dataset" and "Catalog").

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
- measure facts on the data and show them to the analyst (types, distinct values, ranges,
  rows per day). A measured fact is evidence for the analyst. It is not a definition.

If a definition is missing, ask for it. Do not fill the gap. If you think that a definition
is wrong, show the evidence from the data and let the analyst decide.

## Steps

1. **Source.** Ask where the data comes from, how it is published (file, API), how often, and
   under which licence. Fetch a sample.
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
   A check of `checks.yaml` can be an example too (`- check: <name>`): pick the checks whose
   SQL shows a trap that the other examples don't. Five examples at most; `describe` prints
   them all.
7. **Check.** Validate the descriptor (`adele-server validate`), run the fetch on a short
   window, run it again (it must change nothing), then backfill. Profile the stored data:
   gaps per series, days of the clock change (23 and 25 hours), extremes, the first day of
   each change of resolution. Compare two or three figures with a report that publishes them
   (e.g. EPEX's monthly averages); a figure that differs is a finding.
8. **Review.** Propose to run the skill `review-dataset` before the dataset is published.

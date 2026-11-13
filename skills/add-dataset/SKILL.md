---
name: add-dataset
description: Add a new dataset to adele. Use when a data analyst wants to add a source to the adele catalog. The analyst writes the definitions by hand; this skill places them in datapackage.yaml, writes fetch.py and runs the checks.
---

# Add a dataset to adele

Draft, written before adele runs. Update it with the first dataset.

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
2. **Measure.** Profile the sample (DuckDB `SUMMARIZE`, distinct values of text columns, rows
   per day, duplicates on the candidate key). Show the result to the analyst.
3. **Traps.** Go through `skills/common-traps.md` with the analyst, one question at a time.
   Each answer becomes either a step of normalization in `fetch.py`, or a sentence written by
   the analyst for a field description or for `adele.warnings`. Prefer normalization: a trap
   that a column removes is better than a trap that a sentence explains.
4. **Definitions.** Collect the analyst's text for each item of the list above. Place it in
   `datapackage.yaml` following the rule "Keys or prose" of SPEC.md.
5. **fetch.py.** Write `fetch(start, end)`. Apply the conventions of SPEC.md: UTC, timestamp
   at the start of the interval, half-open intervals, one unit per field.
6. **Example queries.** For each question that the analyst gives, write the SQL, run it, and
   show the result. The analyst confirms the result before the entry gets a `verified_at`.
7. **Check.** Validate the descriptor, run the fetch on a short window, compare the schema of
   the result with the descriptor.
8. **Review.** Propose to run the skill `review-dataset` before the dataset is published.

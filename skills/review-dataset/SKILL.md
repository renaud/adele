---
name: review-dataset
description: Review an adele dataset before it is published, or after its descriptor changed. Use to find traps that the descriptor does not cover. Runs several critics that test the descriptor against the data, a blind test, and a reproduction of published reports.
---

# Review a dataset of adele

Draft, written before adele runs. Update it with the first dataset.

Goal: find the traps that nobody wrote down. A critic that only reads the descriptor finds
unclear wording. The unwritten traps are in the data and in the documentation of the source,
so every critic works on the data.

Use the most capable model available, and run the critics as separate agents (a workflow), so
that no critic sees the conclusions of another. Give each critic the data and its task. Do
not give it the author's opinion of the descriptor: a critic that receives a conclusion tends
to confirm it.

## Before you start

Tell the data analyst what you propose to do (the four checks below) and ask:

- "Do you have reports or analyses of your own that I can check the data against?"
- "Which published reports use this data?" Propose the ones that you find (see check 3).

## The checks

1. **Claims against data.** For each statement of the descriptor, write a query that could
   prove it wrong, and run it. Key unique? Values within the declared codes? Declared
   resolution in every period (rows per day over time)? Days of the clock change with 23 and
   25 hours? Units plausible (ranges)? Coverage without gaps?
2. **Common traps.** Go through `skills/common-traps.md`. For each trap, check on the data
   whether it applies, and whether the descriptor or the ingestion handles it.
3. **Reproduce reports.** Search for published reports that use the same data (the source's
   own statistics, annual reports of the system operator, national energy statistics, press
   figures). Take figures from them (a yearly total, a monthly average, a maximum) and compute
   the same figures with `adele query`. Do the same with the analyst's own reports. A figure
   that does not match is a finding: either a trap, or a difference of definition that the
   descriptor should state.
4. **Blind test.** One agent gets only the output of `adele describe` and answers a set of
   questions with `adele query`. A second agent answers the same questions with full access
   to the raw source and to its documentation. Each disagreement is a finding. Take the
   questions from the analyst, from the reports of check 3, and from a third agent that
   writes the questions that a user of this dataset would ask.

## Result

A list of findings. Each one has: what was checked, the query, the expected and the obtained
value, and a proposal:

- normalize at ingestion (preferred when a column can remove the trap)
- a warning or a field description, to be written by the analyst
- no change (with the reason)

The analyst decides on each finding. You do not edit definitions (see the skill
`add-dataset`).

Then:

- add each new kind of trap to `skills/common-traps.md`
- propose the questions whose answers the analyst confirmed as `adele.examples`, and as QA
  questions

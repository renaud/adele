# QA questions: entsoe_day_ahead_prices

Draft by Claude, 2026-11-13, for POC step 5 (TODOs.md). Renaud accepts or rejects each
question, and each answer.

Answers are not computed yet. They must come from a path that doesn't go through adele (the raw
ENTSO-E data, or a figure published elsewhere). An answer computed with adele can't test adele.

The trap column is for the reviewer. The agents under test only get the skill and the CLI, and
never see this file.

| # | question | trap |
|---|---|---|
| 1 | What was the average day-ahead price in Switzerland in 2024? | none (baseline) |
| 2 | What was the average day-ahead price in Germany in 2017? | zone code: DE_AT_LU until 2018-09-30 |
| 3 | What was the average day-ahead price in Germany in 2018? | zone split on 2018-10-01: two codes in one year |
| 4 | What was the average French day-ahead price in the second half of 2025? | resolution changes on 2025-09-30: plain average against time-weighted average |
| 5 | How many hours had a negative day-ahead price in Germany in 2025? | 15-minute rows from 2025-10-01: a row is not an hour |
| 6 | Which delivery day had the highest average day-ahead price in France in 2022, and what was that average? | delivery day in local time, not UTC |
| 7 | What was the Swiss day-ahead price for 08:00-09:00 on 30 March 2026? | local time after the clock change (UTC+2) |
| 8 | How many price intervals did Switzerland have on 25 October 2026? | 25-hour day |
| 9 | What was the average Swiss day-ahead price on each day from 1 to 7 November 2026, and over the whole week? | CH moves to 15 minutes on 2026-11-04: per day fine, the week mixes resolutions |
| 10 | What was the average spread between the Swiss and the French day-ahead price in 2025? | from 2025-09-30, FR is 15-minute and CH hourly: a join on delivery_start keeps one French quarter-hour per hour |
| 11 | Until which delivery day are Swiss day-ahead prices available? | freshness, local delivery day |
| 12 | What was the average Swiss day-ahead price over the last 7 days? | relative to now; incomplete days at both ends |

## Pilot run, 2026-11-13

Before Renaud accepted the questions: one run per question, in a headless Claude Code session
(`claude -p`, default model) whose only tools were the skill `adele` and `Bash(adele:*)`; file,
web and agent tools were disabled, so the agent could not read this file or the descriptor.
Server: the dev server on the Mac, data as of 2026-11-13 12:01 UTC. Cost 0.17 to 0.27 USD and 20
to 37 s per question, 6 to 8 turns. Every agent loaded the skill, ran `adele list`, then
`adele describe`, then one to three queries.

Reference: computed with entsoe-py's pandas client from ENTSO-E (another download and parse
path, not adele), `scratchpad/qa_reference.py` of the session.

| # | agent's answer | reference | trap handled? |
|---|---|---|---|
| 1 | 75.96 EUR/MWh (8,784 hours, local year) | 75.95 (8,783 h: entsoe-py drops one hour, see below) | - |
| 2 | 34.19, zone DE_AT_LU | 34.19 | yes: mapped Germany 2017 to DE_AT_LU |
| 3 | 44.47 = DE_AT_LU (41.73, 6,551 h) + DE_LU (52.60, 2,209 h) | 44.47 (41.73, 52.60) | yes: joined both codes |
| 4 | 55.52 time-weighted (plain average 59.30) | 55.52 (plain 59.29: entsoe-py makes FR's 2025-09-30 hourly) | yes: weighted, explained why |
| 5 | 575 h (time with a negative price); 576 or 588 under other definitions of an hour | 574.75 h | yes: gave the three definitions |
| 6 | 2022-08-30, 743.84 | 2022-08-30, 743.84 | yes: local day |
| 7 | 149.06 (06:00 UTC = 08:00 CEST) | 149.06 | yes |
| 8 | 25 | 25 | yes |
| 9 | week 278.06 time-weighted (plain 279.40), days 254.15 to 290.52 | 278.06 (plain 279.40) | yes |
| 10 | +40.61 (CH above FR), FR averaged to hours before the join | 40.62 (8,759 h: one hour dropped by entsoe-py) | yes: no quarter-hour join |
| 11 | delivery day 2026-11-14 | 2026-11-14 (adele coverage) | yes |
| 12 | 276.83 over 7-13 Nov (incl. today), 285.62 over 6-12 Nov | - (depends on the reading) | gave both readings |

Every answer matches its reference to 0.01 or better. The differences of 0.01 come from the
reference path: entsoe-py's pandas client drops the hour 2024-12-31 00:00 CET (one hour per
year, probably at the border of its yearly requests) and returns the hour at the requested end;
on the hours that both have, the prices are identical. December 2025 also matches EPEX's monthly
report (CH 114.09, DE-LU 93.47, FR 68.73).

What the pilot does not show: with one run per question, it can't tell how often an agent
fails. Twelve runs without a failure are still likely (28 %) if each run fails one time in ten.

## Second set (draft, 2026-11-13): questions the skill doesn't hint at

| # | question | what it tests |
|---|---|---|
| 13 | What was the average day-ahead price in Austria in 2020? | not in the dataset (AT is its own zone since 2018-10-01): say so, don't substitute DE_LU |
| 14 | What was the average intraday price in Switzerland in 2025? | not in the dataset (day-ahead only) |
| 15 | What was the average peak price in Germany in 2024? | the definition of peak (EPEX: Monday to Friday, 08:00-20:00 local) must be stated |
| 16 | In 2022, on how many delivery days was the Swiss daily average day-ahead price below the French one? | join of two zones by local day |
| 17 | What was the largest change in the German day-ahead price between two consecutive hours in 2024? | window function within one zone, ordered by time |
| 18 | What was the volume-weighted average day-ahead price in France in 2023? | not computable (no volumes): say so |
| 19 | What was the average German day-ahead price from 29 September to 5 October 2025? | mixed resolution again, and FR's early switch must not leak into DE |
| 20 | Which of Switzerland, Germany and France had the most hours with a negative day-ahead price in 2024, and how many? | three zones, Germany = DE_LU in 2024 |

Run 2026-11-13 (one run each, same setup as the pilot; transcripts in
`qa/runs_nosync/20261113-132052/`). Reference: SQL directly on the Parquet files (the stored
prices equal entsoe-py's on every common hour).

| # | agent's answer | reference | ok? |
|---|---|---|---|
| 13 | can't answer: no AT series after 2018-09-30; DE_LU is not a stand-in. Added "from memory, roughly 33 EUR/MWh, not checked" | not in the dataset | yes, but see the memory figure |
| 14 | can't answer (day-ahead only); gave the CH day-ahead average 101.69, labelled as another market | not in the dataset | yes |
| 15 | 87.85 (Mon-Fri 08:00-20:00 local, holidays included, stated) | 87.85 (3,144 h) | yes |
| 16 | 136 of 365 days | 136 | yes |
| 17 | +423.81, 2024-12-12 07:00 CET (176.18 --> 599.99) | +423.81 | yes |
| 18 | can't (no volumes); gave the time-weighted 96.86, labelled | not computable | yes |
| 19 | 79.17 time-weighted (plain 64.39, explained as wrong) | 79.17 (plain 64.39) | yes |
| 20 | DE_LU 457 h, FR 352, CH 292 | 457, 352, 292 | yes |

20 of 20 answers right over both sets, one run each. What that supports: with 20 runs and no
failure, a failure rate of 15 % per run or more would have shown at least one failure 96 times in
100 (0.85^20 = 0.04), so it is unlikely; a rate of 5 % would still give 20 clean runs 36 times in
100 (0.95^20 = 0.36). So the pilot rules out frequent failures, not rare ones.

## Run 2026-11-15, after D31 (five examples, four of them published figures)

Rerun of the 20 questions because the card and the skill changed (D12). Same setup as above,
one run each, dev server on the Mac with data last fetched 2026-11-13 20:05 UTC. Transcripts in
`qa/runs_nosync/20261115-202037/`.

- 20 of 20 answers match the references above. q11 and q12 depend on the day: references from
  the stored data, delivery day 2026-11-14 and 272.04 (2026-11-08 to 2026-11-14), both matched.
- Every agent called `describe`. 8 of 20 answers use a published figure of the card: to
  cross-check (q01 names ElCom's 75.95 for the mean of daily means, q05 RTE's definition of a
  negative hour, q20 SMARD's 457), or to say that the card has none for that year (q02).
- q13 and q18 gave no figure from memory this time (on 2026-11-13, q13 did). One run each, so
  this can't be put down to the change.
- q11 and q12 found that the data was a day and a half old while the status said `ok`: `stale`
  is not built (V0, "Not in the POC"). On steacher1 the timers fetch every hour.
- Cost: 4.59 USD against 4.31 (+7 %); 17 of the 20 questions cost more. If nothing had changed,
  each question would cost more or less with even odds, and 17 or more of 20 would happen about
  1 time in 800 (sign test), so the rise is real. The longer card is the likely cause, but the
  skill also grew and the client or model may have changed since 2026-11-13.

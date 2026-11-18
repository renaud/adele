# WP4: files that the source overwrites or revises

Draft by Claude, 2026-11-15. From `PLAN.md` (WP4), `TODOs.md` (Swissgrid),
`docs/datasets-inventory.md` (G4, G5, G6, section 3.1), D23, D24, D25, D27, D30, the poller
(`swissgrid_poll.py`) and its archive. The measures below are new (section "What the poller's
archive shows"). Renaud's answer of 2026-11-15: "all points 1-8 ok"; for point 5 Claude chose
P800D. Decision D33.

## Where WP4 stands (2026-11-15)

- Built in the worktree `wp4` (branch `wp4`, from `13f2b58`), with tests on synthetic data:
  raw answers (G4), the import of kept answers (point 8), the three datasets. G6 needed no code
  (point 5). Decision D33. Reviewed by a fresh agent, 8 findings fixed (log). 374 tests pass.
- In `main` since 2026-11-15 (6d213e9), after WP2 (D32) and the commit "towards WP5": the
  rebase moved the window and partition of the import's calls to the table (D32). 408 tests
  pass in `main`. What a branch from before may hit: `TODOs.md`, "For other sessions".
- Tried on the Mac, in a data folder of the session's scratchpad: the import of the poller's
  copy of 2026-10-17, one real fetch of TSI and daily files, the backfill of the year files
  (log below). Nothing ran on the server.
- Next: step 6, once WP1 is done (2026-11-22 at the earliest). Before it, Renaud confirms the
  three points under "To confirm before the server".

## Goal

adele fetches Swissgrid's three balance files itself, keeps each answer as received for the
two files that overwrite themselves, keeps every version of their rows, and the poller stops
fetching them. The mechanisms also serve 5 more datasets of WP6 (below, "Not in WP4").

The three datasets (ids to be decided; `swissgrid_` as a prefix, like `entsoe_`):

| dataset | file | what an answer holds | refresh |
|---|---|---|---|
| TSI | `total-system-imbalance.csv` | one quarter-hour as three 5-minute values; replaced every 15 minutes | every minute (decided) |
| daily | `control-area-balance-daily.csv` | 96 quarter-hours, the last 24 h: TSI, aFRR, mFRR, NRV, FRCE, provisional price | every 5 minutes, as the poller |
| year | `control-area-balance-<year>.csv` | the same 13 columns for every quarter-hour of the local year so far | once a day (point 5) |

## What the poller's archive shows (measured 2026-11-15)

The poller runs from cron on the server since 2026-09-27, as another user: the agent user can't
read that user's home. The measures use the copy on the Mac
(`_EnTr/class_/Pinson_31761_Renewables_in_Electricity Markets/practice/PhaseThreeSwissgridImbalance/data/`),
which ends on 2026-10-17 12:35 UTC: 20.1 days. The poller keeps an answer when its sha256
differs from the last kept answer of that file, gzipped, one file per answer. Scripts in the
scratchpad of this session, not kept.

**Space.** Per year = the 20 days times 18.2.

| file | kept answers in 20 days | gz on disk | per year, gz | files per year |
|---|---|---|---|---|
| TSI | 2,158 | 0.27 MB | 5 MB | 39,000 |
| daily | 1,795 | 8.5 MB | 155 MB | 33,000 |
| year file 2026 | 23 | 26.6 MB | about 0.3 GB (1) | 420 |
| `secondary-daily.csv` (`afrr_1s`, not in WP4) | 21 | 97.8 MB | 1.8 GB | 380 |

(1) The file grows through the year: 1.2 MB gz per answer in October, 1.7 MB at the end of
2025. The server has 8.6 GB free; weathernext3 alone adds about 65 MB a day (WP1 log), so about
24 GB a year. The raw answers of TSI and daily come to 0.16 GB a year.

**Identical answers.** 306 of the 2,158 kept TSI answers are equal to an earlier kept answer
that is not the one just before (A --> B --> A): Swissgrid's server sometimes serves the
previous file again for a minute. None in the daily and year files.

**TSI quarter-hours missing.** 80 of the 1,932 quarter-hours in those 20 days are in no kept
answer (4.1 %). For each, the poller's log in the 15 minutes during which that quarter-hour
should have been served: network errors only for 46 (most on 2026-10-15 and 10-16, 703 errors
in two days), "not modified" only for 33 (Swissgrid kept the previous file), both for 1. So the
poller asked; a fetch every minute does not give every quarter-hour.

**The daily file revises its rows.** 34 of its 2,029 quarter-hours changed once after their
first publication; the change came a median of 57 minutes after the start of the quarter-hour,
at most 24 h 35 min. 13 of them were first published with every component blank and only a TSI
value, then filled (SED's README found the same in the year file); the other 21 changed values
that were already there (2 of them the price only).

**The year file against the daily file.** Same header, same 13 columns. The year file reaches
to about 2 h before the time at which it changes, and it changed about once a day (23 answers).
On the 1,972 quarter-hours that are in both:

- the last daily answer against the latest year answer: 1 quarter-hour differs (TSI by 0.1 MW).
- the last daily answer against the first year answer that holds the quarter-hour: 4 differ (the
  provisional price by up to 8.17 ct/kWh, which is 81.7 EUR/MWh).
- within the year file: 5 quarter-hours changed in 20 days, at most 3 days after delivery. SED
  also found 10 prices that changed 4 to 7 weeks after delivery (by up to 1.5 EUR/MWh), between
  2026-10-17 and 10-28, and the files of 2024 and 2025 were last modified on 2026-03-24.

## What is settled

- The two datasets of TSI and daily, and `every: PT1M` for TSI (above).
- D23: no journal, no SQLite file, no bookmark until a dataset needs one. WP4 needs none (point
  3): the TSI answer is 120 bytes, and the year file is asked once a day.
- D24: a query reads only the folders of the tables.
- D30: `append-only` stores a version when a key is new or a value differs from the latest
  version; `fetched_at` is the time at which `fetch.py` returned.
- SPEC.md, Adding a dataset: "A connector never writes files", and `fetch.py` gets every dataset
  from its source.

## Design

### Raw answers (G4)

1. **Who writes a raw answer, and when.** G4 is there for one case: the parser fails or is
   wrong, and the source has already replaced the file. So the answer must be kept before it is
   parsed, also when the parse fails or the time limit stops the child.
   - (a) Split `fetch.py` in two for such a dataset: `download(start, end)` yields answers
     (name, url, bytes), `parse(answers)` returns the tables, as `fetch` does today. The runner
     writes each answer to the work folder as soon as it is yielded, with the time it got it;
     the server moves them into the archive whatever the outcome. A parser fixed later can run
     again on the kept answers (point 8 uses this to import the poller's archive). Cost: a second
     shape of `fetch.py`, a few dozen lines in the runner and the server. Risk: low; the other
     datasets keep `fetch(start, end)`.
   - (b) The server gives `fetch.py` a folder, and `fetch.py` writes each answer there before it
     parses it. Cost: smaller than (a). Risk: nothing checks that the bytes are the ones
     received, and "a connector never writes files" gets an exception. No parse of old answers
     without a second entry point anyway.
   - (c) The server downloads: the descriptor lists the URLs, `fetch.py` only parses. Risk: high.
     Swissgrid's URL changes when it replaces a file (the `/dam/jcr:<id>/` part), and the poller
     finds it again on three web pages. That logic would move into the server.

   Recommended: (a). A dataset says it in its descriptor (`adele.raw: keep`, name to settle);
   `validate` refuses the key without `download` and `parse`, and the reverse.

2. **Where the answers are stored.** `<data_dir>/<id>/raw/<YYYY-MM-DD>/<received_at>_<name>.gz`,
   one gzipped file per kept answer, as the poller does, and one `manifest.csv` per day folder
   (received_at, name, url, bytes, sha256), one line per kept answer. The folder is not a table
   folder, so queries can't read it (D24). It is part of the data folder for backups. The
   manifest is not a journal of requests (D23): an answer that is not kept leaves no line.
   Rejected: a Parquet table with the bytes in a column (one file per month, rewritten at each
   fetch; the 30 MB answers of `afrr_1s` make that heavy later).

3. **Identical answers.**
   - (a) Keep every answer: TSI would be 1,440 files a day for about 100 new ones.
   - (b) Skip an answer equal to the last kept answer of the same name, as the poller (the
     sha256 is in the last line of the manifest: computed from the files, so D23 holds).
     Keeps the 306 A --> B --> A answers of TSI: 14 % more files, 37 kB in 20 days.
   - (c) Skip an answer equal to any answer kept in the last 24 h. Removes those 306, and also
     the trace that the server went back to an older file.

   Recommended: (b). No conditional request (ETag, If-Modified-Since): the poller needed it for
   18 to 26 MB files asked every hour; the files of WP4 are 120 bytes every minute, 11 kB every 5
   minutes, 3 MB once a day.

4. **How long.**
   - (a) For ever. TSI and daily: 0.16 GB and 72,000 files a year (table above).
   - (b) A retention per dataset (`adele.raw: {keep: P90D}`), deleted by the server once the
     rows parsed from them have passed their checks.

   Recommended: (a) now; (b) when `afrr_1s` comes (1.8 GB a year). And no raw answers for the
   year file: its revisions are kept parsed by `append-only`, and Swissgrid still serves the
   file. What that gives up: if the parser misreads a value that Swissgrid revises later, the
   version that adele stored is wrong and the original is gone. A check that fails (WP8) would
   show the misread; a backfill would then bring only the current file.

### Whole files revised in place (G6)

5. **A lookback that covers the whole file.** Today a fetch keeps only the rows in
   [last - lookback, now + horizon) (`_stage`). A year file revised 6 weeks back loses the
   revision when the lookback is 3 days.
   - (a) A long lookback, and nothing to build: `fetch.py` downloads the year files of the local
     years that the window touches, and the server compares every row in the window. With
     `lookback: P800D`, that is three files (2024 to 2026: 0.7 + 4.6 + 3 MB) a day, which covers
     a revision like that of 2026-03-24 in the file of 2024. Checked in the code: the duration
     parser takes P800D, and `merge_versions` writes only the partitions that have a new
     version. D25 then retries a failing run for 800 days, which does no harm.
   - (b) `lookback: all` (inventory, section 5, item 11): the server keeps every row that
     `fetch.py` returns. Cost: a change of `catalog.py`, `scheduled_window` and `_stage`. It fits
     a file with the whole history (IGRA2, DWD `wlk_daily`, WP6), not a series of year files:
     `energy_statistic` would download 17 files of about 20 MB every day.

   Recommended: (a) for WP4, with a lookback that Renaud chooses (P800D, or P400D for the current
   and the previous year only). (b) when the first file with the whole history comes. Detail for
   the build: when the year file changes (around 00:00 or 04:00 UTC, by the poller's hourly
   answers), to choose the time of the daily fetch.

6. **The year file: its own dataset, or the same table as the daily file?**
   - (a) The same table. A dataset has one `every` and one `lookback` (`adele.refresh`), and the
     two files need 5 minutes and 1 day, 1 day and about 800 days. One `fetch.py` would then
     download 3 MB every 5 minutes (860 MB a day), or decide by the clock which file to ask,
     without memory (D23). And a table belongs to one dataset (D8): two datasets can't write it.
   - (b) Two datasets with the same columns. The year table is the history; the daily table
     holds the last 24 h with the first published values (the placeholders and their filling),
     and the most recent hours that the year file doesn't have yet. Their values agree (1
     quarter-hour of 1,972 differs at the latest answer). Cost: the definitions are written
     twice, or the second refers to the first. Risk: an agent adds the two tables together; a
     warning in each says which one to use for what.

   Recommended: (b). A view that combines them would be a derived table (G11, out for now).

### The hand-over from the poller

7. **When adele takes over, and how long both run.** The poller fetches 9 files and harvests the
   monthly price files; WP4 covers 5 of them (TSI, daily, the year files of 2024 to 2026).
   - (a) File by file: adele fetches a file next to the poller for 7 days, a script compares
     the two (every quarter-hour that the poller has is in adele with the same values, and the
     count of what each one missed), then Renaud removes the file from the poller's `SOURCES`.
     The poller keeps the files that adele doesn't fetch yet. Cost: one comparison script, and
     Renaud's edit of the poller. Risk: low; two clients ask Swissgrid for 120 bytes a minute.
   - (b) The poller stays the downloader, and adele reads its archive (the inventory's open
     question 4). Against it: two systems for good, a poller without status, alerts or sandbox,
     and a fetch unit that would need to read the home of the poller's user.
   - (c) Switch at once. Risk: a defect of adele in the first days loses data that nobody else
     has.

   Recommended: (a). Start: after WP1's week (2026-11-22) at the earliest, since the server runs
   32237db and WP4 needs `main` with WP3 and WP4. The comparison can't ask for 100 % of the
   quarter-hours (the poller missed 4.1 %): it asks that adele misses none that the poller got,
   outside a restart of adele.

8. **The poller's archive in adele.** With point 1 (a), `parse` can read the poller's answers,
   so adele's history of TSI and of the daily file can start on 2026-09-27 instead of at the
   hand-over. The 5-minute values exist nowhere else.
   - (a) Import as versions, with the time of each answer as `fetched_at` (from the poller's
     file name): a command that reads the answers in time order, parses each one and merges it,
     then copies the answers into `raw/`. It runs before adele's first scheduled fetch of that
     dataset (D30 refuses a stamp older than a stored one), and `versions_since` becomes the
     poller's start. A new decision next to D30, which says that `fetched_at` is set when
     `fetch.py` returns.
   - (b) Import as a backfill: every row gets one stamp, before `versions_since`. Loses the first
     published values of the daily file and the time at which each TSI value appeared.
   - (c) No import: the archive stays as files.

   Recommended: (a). It needs the archive on the server in a place that adele can read: Renaud
   copies it (1.3 GB on 2026-10-17, of which 1.2 GB is the `history/` snapshot, not needed).

## Steps

1. **Decide** points 1 to 8. Done: Renaud, 2026-11-15; D33. The text for SPEC.md is below.
2. **Build G4** with tests on synthetic data. Done (`server/tests/test_raw.py`): an answer kept
   when `parse` fails, when the time limit stops the child, when the merge fails; an identical
   answer skipped, A --> B --> A kept three times; two answers in one call; a name that is not a
   file name; the archive out of reach of `read_text`, `read_blob`, `read_csv`.
3. **G6.** Done: with P800D a revision 6 weeks back reaches the `_versions` view and only its
   month is written again; with P3D it is lost (the gap of the inventory).
4. **The three datasets.** Done: `datasets/swissgrid_tsi`, `swissgrid_balance_daily`,
   `swissgrid_balance`, descriptors with definitions drafted by Claude (marked), parsers tested
   on synthetic files (`server/tests/test_swissgrid_fetch.py`). No `checks.yaml` yet (log,
   choice 6).
5. **Import** (point 8). Done on the Mac with the copy of 2026-10-17. On the server: with the
   whole archive, in step 6.
6. **Side by side** on the server (point 7), after WP1:
   1. Renaud copies the poller's folders `total-system-imbalance/` and
      `control-area-balance-daily/` to a place that the user of adele can read.
   2. `git pull` in `/opt/adele`, `adele-server validate`.
   3. `adele-server import swissgrid_tsi <copy>/total-system-imbalance`, the same for the daily
      file; `adele-server backfill swissgrid_balance --start 2024-10-31`.
   4. Renaud enables the three timers (`systemctl enable --now adele-fetch@<id>.timer`).
   5. 7 days, then a comparison script (to write then): every quarter-hour of the poller's
      answers of those days is in adele with the same values, and the count of what each missed.
   6. Renaud removes the three files from the poller's `SOURCES` (the year files of 2024 and
      2025 too).

## Done when

- A dataset with `adele.raw` keeps every answer that differs from the last one, also when its
  parse fails or times out. Tests on synthetic data.
- A revision of the year file older than 3 days reaches the `_versions` view.
- The three datasets fetch on the server on their schedule, with the poller's archive imported.
- 7 days side by side: adele holds every quarter-hour that the poller got, with the same values,
  outside a restart of adele. Then the poller no longer fetches these three files.

## Not in WP4

- The other datasets that need G4 or G6 (WP6): `afrr_1s` (G4; 1.8 GB of answers a year, point 4
  b), `energy_statistic` and `activation_cost` (G6, year files), IGRA2 and DWD `wlk_daily` (G6,
  files with the whole history, point 5 b). `imbalance_prices` fits today (WP5). The poller
  keeps fetching their files until then.
- The other effects of `adele.irreplaceable` that the inventory proposed (section 5, item 10):
  an alert at the first failed fetch (a failed fetch already sets the status to failing) and
  `overwrite` refused.
- What the data means (WP7): units (the price is in ct/kWh in the file), signs, whether a TSI
  value at a 5-minute stamp is an interval or an instant. Published figures (WP8).

## Open questions

None of design: points 1 to 8 accepted by Renaud on 2026-11-15.

### To confirm before the server

Confirmed by Renaud on 2026-11-17 ("1-3 ok"), before the imports on the server of the same day
(step 6: `deploy/backfill.sh swissgrid`; `swissgrid_tsi`: 5,556 answers from 2026-09-27 09:57
to 2026-11-17 16:50 UTC, 16,667 rows, none refused).

Stored versions can't be converted later (answer d of WP3), so these come before the import and
the first fetches on the server:

1. The prices in EUR/MWh (x10 of the ct/kWh of the files, rounded to 0.1), as SED did and as
   the ENTSO-E prices in adele are.
2. The 5-minute TSI stamped at the start of each interval (the mean of the three values matches
   the quarter-hour with start stamps, not with end stamps: measure above).
3. The ids `swissgrid_tsi`, `swissgrid_balance_daily`, `swissgrid_balance`.

## Text for `SPEC.md`

Proposed; Renaud edits `SPEC.md`.

In "Adding a dataset", after the bullet `fetch.py`:

> - A source that overwrites itself (a file that holds only its latest values) declares
>   `adele.raw: keep`. Its `fetch.py` then defines `download(start, end)`, which yields each
>   answer as received, and `parse(answers)`, which returns the tables. The server keeps each
>   answer before `parse` runs, so that a parser fixed later can read it again.

In "Storage", a new bullet:

> - raw answers (`adele.raw: keep`): each answer that differs from the last one of its name is
>   kept as received, gzipped, with its time of reception, URL and sha256, in the data folder
>   of the dataset, where queries can't read it. They are kept for ever and backed up with the
>   data.

In "Revisions", at the end of the bullet `append-only`:

> Versions imported from answers that another program kept (`adele-server import`) carry the
> time at which that program received them; `versions_since` is then the first of them.

## Log

### 2026-11-15, build (worktree `wp4`)

Renaud: "all points 1-8 ok". Decided by Claude during the build:

1. Point 5: P800D, not P400D: it reaches the file of the year before last, which Swissgrid
   changed on 2026-03-24 (three files, about 8 MB per run).
2. The archive is `_raw/`, not `raw/` as point 2 said: a table name can't start with `_`, so a
   table named `raw` can't take the folder.
3. A dataset without `adele.raw` may have a helper named `parse` next to `fetch()`
   (`entsoe_load` and `swissgrid_balance` have one). Refused: the key with a `fetch()`, and
   `download` and `parse` without the key and without `fetch()`.
4. A version is stamped as D30 says, when `fetch.py` returned; an answer carries its own time of
   reception, a little earlier. An import stamps with the time of reception: an archive of adele
   imported again gives the same versions with stamps earlier by milliseconds (tested).
5. The import keeps, for each answer, the window of a scheduled run at its time of reception:
   [received - every - lookback, received + horizon). So it imports what adele would have
   stored, and a row older than that is dropped (tested).
6. No `checks.yaml` for the three datasets. The identity TSI = -(sum of the components) holds
   (3.9e-7 MW in the year files, 1.1e-7 MW in the daily file), but `describe` would call it "1
   figure published by ...", which it is not. For WP8, with its SQL ready:
   `SELECT coalesce(max(abs(tsi + afrr_up + afrr_dn + sa_mfrr_up + sa_mfrr_dn + da_mfrr_up +
   da_mfrr_dn + nrv_import + nrv_export + frce_import + frce_export + coalesce(rr_up, 0) +
   coalesce(rr_dn, 0))), 0) FROM swissgrid_balance.balance` (a placeholder row gives null and
   drops out).
7. The daily table has the columns of the 2026 file, named as in the year table, so that the two
   can be joined or put one above the other by name; the year table has also `rr_*`, the dual
   prices and `price_single_shadow`, as SED had.
8. TSI is `append-only`, not `none`: no value changed in 20 days, but `fetched_at` of the first
   version is the time of publication within a minute, which is what the 5-minute file adds.
9. The year files: a missing file is an error, except the file of the current year in its first
   7 days. The fetch every PT6H gets the version of about 23:20 UTC at 00:00.
10. The URL of each file: the seed of 2026-09-27 (they still answered on 2026-11-15); after a
    404, the file is found by name on two of Swissgrid's pages and the run prints that the seed
    is stale.
11. The checks after each fetch (Renaud's note in `TODOs.md`): 10 ms per run for TSI on the Mac,
    so 1,440 runs a day cost about 15 s. Left as is.
12. `describe` gets two lines: `raw_answers` (kept, from which day to which) and `imported`
    (which versions came from another program).

A bug found during the trial and fixed: `scheduled_fetch` did not add up the count of answers of
its pieces (it printed "0 of 0 answers kept").

### 2026-11-15, trial on the Mac

In a data folder of the session's scratchpad (`wp4-server.toml`), not in `data_nosync/`:

- Import of the poller's copy of 2026-10-17: TSI, 2,158 answers in 24 s, 5,556 rows of 5
  minutes; daily, 1,795 answers in 34 s, 2,063 versions (2,029 quarter-hours and the 34
  revisions). Each answer is in `_raw/`, with the poller's time of reception.
- Then one scheduled fetch of each from swissgrid.ch: TSI 3 rows, daily 95 rows, both answers
  kept; a second fetch of TSI a minute later, "0 of 1 answers kept", 1.4 s for the whole run.
- Backfill of the year files from 2024-10-31: 71,424 quarter-hours to 2026-11-14 22:45 UTC, none
  missing on the grid, 27 s. Equal to SED's `control_area_balance_15min.parquet` on all 69,696
  common quarter-hours, in all 17 columns. The latest year and daily rows differ on 1 of 2,037
  common quarter-hours.

### 2026-11-15, review of the build

A fresh agent reviewed the diff (8 findings; nothing serious on the path that keeps answers:
each failure keeps them). Claude checked each against the code; all hold, all fixed, each with a
test (374 tests pass):

1. One answer that `parse` can't read stopped the whole import, at every run, without naming
   the file. Now each group is parsed on its own; a failed group is kept in the archive, listed
   with its files and error ("not merged"), and the import goes on and exits with 1.
2. The year parser accepted a file with a known column missing, and would have stored a null
   version of every row of the 800 days. Now a file must match one of the three layouts exactly.
3. `import` with a relative folder failed (the child runs in the dataset's folder). Resolved.
4. A name that is not a string (2026) passed the runner's check and its answer was then dropped
   without failing the fetch; a name with a final newline passed too. Now a name is a string that
   matches whole, and a line of `answers.jsonl` that can't be read fails the fetch (only a last
   line cut by the end of the child is skipped).
5. After a fetch with `--start`/`--end` or a backfill, an import skipped every older answer and
   exited with 0. Now refused, with the time of the newest version fetched by adele.
6. A hard stop between two partitions of one group of an import left the other partition
   without that version for good. Now `imported` is written before each merge, and a second run
   merges that group again (`merge_versions(resume=True)`).
7. Ctrl-C during a fetch whose answers then failed to be kept became an ordinary failure. Now
   only an Exception is replaced. Errors of the archive and of storage in `import` print as
   `error:` lines, not tracebacks.
8. A local-time year file that ends inside the repeated hour of October would have stored its
   summer-time stamps as winter time. Now the side of the change is read from the order of the
   rows, and the converted stamps must increase.

The trial on the Mac was run again in a new folder with the fixed code: the same numbers, and a
second import of TSI merged only the last group again ("2157 older", "0 new or changed").

# adele: how to work on it

adele serves datasets to agents: a server fetches and stores them, a CLI queries them.

- Read first: `SPEC.md` (what adele is), `PLAN.md` (what comes next), `TODOs.md` (open items).
- Layout: `server/` (fetch, storage, HTTP), `client/` (CLI), `datasets/<id>/`
  (`datapackage.yaml`, `fetch.py`, `checks.yaml`), `skills/`, `deploy/`, `docs/`.
- Test: `cd server && uv run pytest`. Check the descriptors: `uv run adele-server validate`.
- Server: `/usr/local/bin/sc-run '<command>'` runs one command there as the user
  `claude` (no sudo). ssh and scp are refused to agents: never look for another route. Steps
  that need root are scripts in `deploy/` that Renaud reads and runs. Everything about the
  machine (address, accounts, paths outside adele, other services) is in `SERVER.md` at the
  root of the main checkout, which is not in git (a worktree doesn't have it): new facts go
  there, not into tracked files.
- A dataset: add it with `skills/add-dataset`, review it with `skills/review-dataset`. Its QA is
  a list of published figures in `checks.yaml`.
- What the data means is written by Renaud. A draft by an agent is marked `# draft by Claude`.
- A decision is a new entry at the end of `DECISIONS.md`; never change an old one. `SPEC.md` is
  edited by Renaud: propose the text.
- Tests use synthetic data, never a real source. The data is in `data_nosync/`, not in git.
- Commit only when asked. Write "adele" in lower case.

"""Raw answers (G4, D33): each answer of a source, kept as received, for a dataset that declares
`adele.raw: keep`.

Such a dataset's fetch.py defines `download(start, end)`, which yields the answers, and
`parse(answers)`, which returns the tables. The runner writes each answer to the work folder as
soon as `download` yields it (`answers.jsonl` names them), before anything parses it; the server
then moves them here, whatever came after: a parse that failed, a time limit, a merge that failed.

The archive of a dataset is `<data_dir>/<id>/_raw/<YYYY-MM-DD>/`, one folder per UTC day of
reception, with one gzipped file per kept answer and one `manifest.csv` (one line per kept
answer). A table name can't start with `_`, so the folder is never a table folder, and a query
can't read it (D24). An answer equal to the last kept answer of the same name (sha256) is not
kept again. Nothing else is written: an answer that is not kept leaves no trace (D23).
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("adele.raw")
UTC = dt.timezone.utc

ARCHIVE = "_raw"
MANIFEST = "manifest.csv"
FIELDS = ["received_at", "name", "file", "url", "bytes", "sha256"]
ANSWERS = "answers.jsonl"  # in the work folder: one line per answer that download() yielded
# The name of an answer: a file name, e.g. total-system-imbalance.csv. It goes into a file name.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Kept answers, as this module names them, and as the Swissgrid poller named them
# (<stem>/<YYYY-MM-DD>/<YYYYMMDDTHHMMSSZ>.<ext>.gz, the name being <stem>.<ext>).
_ADELE_FILE = re.compile(r"^(\d{8}T\d{6}\.\d{6}Z)_(.+)\.gz$")
_POLLER_FILE = re.compile(r"^(\d{8}T\d{6}Z)\.([A-Za-z0-9]+)\.gz$")


class RawError(Exception):
    pass


@dataclass
class Answer:
    name: str
    received_at: dt.datetime
    url: str | None
    path: Path  # the file that holds the body: plain in a work folder, gzipped in an archive


def archive_dir(data_dir: Path, ds_id: str) -> Path:
    return data_dir / ds_id / ARCHIVE


def check_name(name) -> str:
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):  # fullmatch: `$` would let a final newline in
        raise RawError(f"the name of an answer must match {NAME_RE.pattern} (a file name), got {name!r}")
    return name


def stamp(t: dt.datetime) -> str:
    return t.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


def _days(arch: Path) -> list[Path]:
    if not arch.is_dir():
        return []
    return sorted(d for d in arch.iterdir() if d.is_dir() and _DAY_RE.match(d.name))


def last_sha256(arch: Path, name: str) -> str | None:
    """The sha256 of the last kept answer of that name: the newest day folder whose manifest has it."""
    for day in reversed(_days(arch)):
        m = day / MANIFEST
        if not m.exists():
            continue
        with open(m, newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("name") == name]
        if rows:
            return rows[-1]["sha256"]
    return None


def keep(arch: Path, name: str, url: str | None, body: bytes, received_at: dt.datetime,
         last: dict[str, str | None]) -> bool:
    """Keep one answer, unless it equals the last kept answer of its name. `last` caches the sha256
    of the last kept answer per name within one call. Returns whether the answer was kept."""
    check_name(name)
    sha = hashlib.sha256(body).hexdigest()
    if name not in last:
        last[name] = last_sha256(arch, name)
    if last[name] == sha:
        return False
    received_at = received_at.astimezone(UTC)
    day = arch / f"{received_at:%Y-%m-%d}"
    day.mkdir(parents=True, exist_ok=True)
    fname = f"{stamp(received_at)}_{name}.gz"
    if (day / fname).exists():  # an import that reads this archive again: the same answer is there already
        if hashlib.sha256(gzip.decompress((day / fname).read_bytes())).hexdigest() == sha:
            last[name] = sha
            return False
        raise RawError(f"{day / fname} exists already with another content: two answers named {name!r} "
                       "received at the same time")
    tmp = day / f".{fname}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(gzip.compress(body, mtime=0))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, day / fname)
    manifest = day / MANIFEST
    new = not manifest.exists()
    with open(manifest, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({"received_at": received_at.isoformat(), "name": name, "file": fname, "url": url or "",
                    "bytes": len(body), "sha256": sha})
    last[name] = sha
    return True


def work_answers(folder: Path) -> list[Answer]:
    """The answers that the runner wrote to a work folder, in the order of download().

    The runner writes the body, then one line ending with a newline. Only a last line without its
    newline may be cut (the child stopped by the time limit or a signal): it is skipped. Any other
    line that can't be read, or whose body is missing, raises RawError: an answer that the runner
    accepted must not be lost without the fetch failing."""
    path = folder / ANSWERS
    if not path.exists():
        return []
    text = path.read_text()
    lines = text.split("\n")
    if lines[-1]:
        log.warning("%s: skipped a last line cut by the end of the child: %r", path, lines[-1][:200])
    out = []
    for line in lines[:-1]:
        try:
            a = json.loads(line)
            ans = Answer(check_name(a["name"]), dt.datetime.fromisoformat(a["received_at"]), a.get("url"),
                         folder / check_name(a["file"]))
        except (ValueError, KeyError, TypeError, RawError) as e:
            raise RawError(f"{path}: a line can't be read ({e}): {line[:200]!r}") from e
        if not ans.path.exists():
            raise RawError(f"{path}: the body of {ans.name} received at {ans.received_at} is missing")
        out.append(ans)
    return out


def keep_work_answers(data_dir: Path, ds_id: str, folder: Path) -> tuple[int, int]:
    """Move the answers of a work folder into the archive of the dataset: (yielded, kept)."""
    arch, last, kept = archive_dir(data_dir, ds_id), {}, 0
    answers = work_answers(folder)
    for a in answers:
        kept += keep(arch, a.name, a.url, a.path.read_bytes(), a.received_at, last)
    return len(answers), kept


def read_body(a: Answer) -> bytes:
    data = a.path.read_bytes()
    return gzip.decompress(data) if a.path.suffix == ".gz" else data


def find_answers(folder: Path) -> list[Answer]:
    """Every kept answer under `folder`, oldest first: files named as this module names them, or as
    the Swissgrid poller did. Other files are ignored. The URL comes from a manifest when there is
    one next to the file."""
    out = []
    for p in folder.rglob("*.gz"):
        m = _ADELE_FILE.match(p.name)
        if m:
            t = dt.datetime.strptime(m.group(1), "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=UTC)
            out.append(Answer(m.group(2), t, None, p))
            continue
        m = _POLLER_FILE.match(p.name)
        if m and _DAY_RE.match(p.parent.name):
            t = dt.datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            out.append(Answer(f"{p.parent.parent.name}.{m.group(2)}", t, None, p))
    urls = {}
    for m in folder.rglob(MANIFEST):
        with open(m, newline="") as fh:
            urls.update({(m.parent / r["file"]): r["url"] for r in csv.DictReader(fh) if r.get("url")})
    for a in out:
        a.url = urls.get(a.path)
    for a in out:
        check_name(a.name)
    return sorted(out, key=lambda a: (a.received_at, a.name))


def summary(data_dir: Path, ds_id: str) -> dict | None:
    """The first and last day folder of the archive and their count, for describe; None when empty."""
    days = _days(archive_dir(data_dir, ds_id))
    if not days:
        return None
    return {"first_day": days[0].name, "last_day": days[-1].name, "days": len(days)}

#!/bin/bash
# Run QA questions in headless Claude Code sessions that have only the skill `adele` and the
# `adele` CLI (no file, web or agent tools), N at a time. Transcripts: qa/runs_nosync/<stamp>/.
#
# usage: ADELE_URL=... ADELE_API_KEY=... qa/tools/run.sh qa/<dataset>.questions.txt [parallel=4] [runs=1]
# Then: python3 qa/tools/summarize.py qa/runs_nosync/<stamp>
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
QUESTIONS=$(cd "$(dirname "$1")" && pwd)/$(basename "$1"); PAR=${2:-4}; RUNS=${3:-1}
: "${ADELE_API_KEY:?set ADELE_API_KEY}"; : "${ADELE_URL:=http://127.0.0.1:8000}"
OUT="$REPO/qa/runs_nosync/$(date +%Y%m%d-%H%M%S)"; mkdir -p "$OUT"
BOX=$(mktemp -d); mkdir -p "$BOX/.claude/skills/adele" "$BOX/bin"
cp "$REPO/skills/adele/SKILL.md" "$BOX/.claude/skills/adele/SKILL.md"
printf '#!/bin/bash\nexec "%s/client/.venv/bin/adele" "$@"\n' "$REPO" > "$BOX/bin/adele"; chmod +x "$BOX/bin/adele"
export BOX OUT ADELE_URL ADELE_API_KEY
one() {
  local line="$1"; local run="${line##*|}"; local rest="${line%|*}"
  local id="${rest%%|*}" q="${rest#*|}"
  cd "$BOX" && PATH="$BOX/bin:$PATH" claude -p "$q" \
    --allowedTools "Bash(adele:*)" "Skill" \
    --disallowedTools "Read" "Glob" "Grep" "WebFetch" "WebSearch" "Task" "Agent" "Write" "Edit" "NotebookEdit" \
    --output-format stream-json --verbose --no-session-persistence --strict-mcp-config \
    > "$OUT/${id}_r${run}.jsonl" 2> "$OUT/${id}_r${run}.err" || true
  echo "${id} run ${run} done"
}
export -f one
for r in $(seq 1 "$RUNS"); do grep -v '^[[:space:]]*$' "$QUESTIONS" | sed "s/\$/|$r/"; done \
  | tr '\n' '\0' | xargs -0 -P "$PAR" -I{} bash -c 'one "$1"' _ {}
echo "transcripts in $OUT"

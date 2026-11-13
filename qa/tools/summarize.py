import json, sys, glob, os
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.jsonl"))):
    cmds, final, meta, denied = [], None, {}, []
    for line in open(f):
        try: ev = json.loads(line)
        except ValueError: continue
        if ev.get("type") == "assistant":
            for b in ev["message"].get("content", []):
                if b.get("type") == "tool_use":
                    inp = b.get("input", {})
                    cmds.append(f"{b['name']}: " + (inp.get("command") or json.dumps(inp))[:400].replace("\n", " "))
        elif ev.get("type") == "user":
            for b in ev["message"].get("content", []) if isinstance(ev["message"].get("content"), list) else []:
                if b.get("type") == "tool_result" and b.get("is_error"):
                    c = b.get("content"); denied.append(str(c)[:160].replace("\n", " "))
        elif ev.get("type") == "result":
            final = ev.get("result"); meta = {k: ev.get(k) for k in ("num_turns", "total_cost_usd", "duration_ms")}
    print("=" * 100); print(os.path.basename(f), meta)
    print("describe called:", any("adele describe" in c for c in cmds), "| skill used:", any(c.startswith("Skill") for c in cmds))
    for c in cmds: print("  >", c)
    for d in denied: print("  ! error:", d)
    print("ANSWER:", (final or "")[:1500])

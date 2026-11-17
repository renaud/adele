# The two figures of the README

The figures are in [README.md](../README.md), section "From a source to an answer":
`overview.svg` (figure 1, from a source to an answer) and `agent-session.svg` (figure 2, what
an agent reads). This page says how to keep them true.

Status: drawn by Claude from SPEC.md, DECISIONS.md and the server code. Figure 2 dates from
2026-11-14 (D1 to D24). Figure 1 was redrawn on 2026-11-17 (D1 to D34), in the layout that
Renaud chose among three: a flow from left to right with few words. Both figures are SVG
files written by hand. To change a text, edit the file.

Figure 1 leaves out on purpose (Renaud, 2026-11-17): a title and a subtitle, a legend, labels
on the arrows, the status, "always on", and what is not built (`adele pull`). The arrows
between boxes are dark grey. The CLI box has the colour of the agent.

Figure 2 has no title inside the image either (Renaud, 2026-11-17): the heading of the README
is its title. Since that day, the commands stand further apart than the lines of one answer,
so that a reader sees four separate calls.

## Keeping the figures true

Update figure 1 when:

- `adele pull` is built: add it as line 4 of the box "adele CLI".
- a dataset comes from a new source: the box "Sources" has one chip for each of the 8 sources
  of `datasets/` on 2026-11-17, and its last line names their kinds (ENTSO-E and Open-Meteo
  are APIs; Swissgrid, Pronovo, MeteoSwiss and Energy-Charts publish files; ECMWF and
  WeatherNext 3 are Zarr stores).

Update figure 2 when:

- D20 is built (the footer shows only the warnings marked for it), or `render.py` prints the
  list, the card or the footer differently. `render.py` changed in the working tree after the
  text was captured (2026-11-14, about 17:15).
- the first warning of `entsoe_day_ahead_prices` (the one on 2025-10-01) is rewritten. The
  figure leaves it out on purpose, because TODOs.md says that Renaud will rewrite it.

How the text of figure 2 was captured, without the HTTP server (run in `server/` with
`uv run python`; check that the functions still have these names):

```python
from adele_server import config as config_mod, engine, render
from adele_server.catalog import load_catalog

cfg = config_mod.load("adele-server.toml")
catalog = load_catalog(cfg.datasets_dirs)
print(render.render_list(cfg, catalog))
print(render.render_describe(cfg, catalog["entsoe_day_ahead_prices"]))
res = engine.run(catalog, cfg.data_dir, cfg.query, sql)
print(render.render_query(res, render.query_footer(cfg, catalog, res.datasets)))
```

The two queries of the figure: the mean price of CH per local year for 2022 to 2024
(`year(delivery_start AT TIME ZONE 'Europe/Zurich')`, `round(avg(price), 2)`), and
`SELECT delivery_start, price` for CH from 2024-01-01 (capped at 100 of 25,968 rows).

Editing the SVG files:

- A CSS rule of the `<style>` block wins over an attribute such as `font-size="22"` or
  `stroke-width="2"` on the element. Sizes and stroke widths are therefore classes.
- The dark colours are the rules inside `@media (prefers-color-scheme: dark)`. Every colour of
  the light variant needs its dark rule.
- Figure 1: the comment at the top of the file gives the two rows and their columns. A small
  drawing (the robot, the person, the drawing of a stage) is a `<g class="ic ...">` that is
  placed with `transform`. Blue is the sources, amber is the dataset folder, and purple is the
  agent and its CLI.
- Figure 1: a text must stay inside its box when the reader's font is wider than the one of
  macOS. On 2026-11-17 the texts fitted with the system fonts and with Verdana as a wide
  stand-in.
- Figure 2: a line of the session holds up to 88 characters. A command starts a block: list
  at y 100, describe at 233, the two queries at 672 and 873. Inside a block, each line is 17
  lower than the one before, and the next command comes 48 after the last line. A note sits on
  the line that it explains, so it moves with its block.

Checking a render (figure 2 was checked on 2026-11-14 with the first and the third way, both
figures on 2026-11-17 with the first and the last; neither in VS Code's preview nor on a git
host):

- `rsvg-convert -z 2 docs/overview.svg -o out.png`, then look at the PNG.
- Dark: render a copy in which the rules of the `@media` block stand outside the block.
- WebKit, with the system fonts: `qlmanage -t -s 1920 -o <dir> <file.svg>`. It crops a wide
  figure to a square, so give the copy a square `viewBox`.
- Chromium, with the system fonts: Playwright's `chrome-headless-shell` with
  `--screenshot=out.png --window-size=960,476 --force-device-scale-factor=2
  --virtual-time-budget=8000` and the path of the SVG file.
- A text that leaves its box (done for figure 1 on 2026-11-17, with a script that was not
  kept): an HTML page that holds the SVG inline, and a script in it that compares `getBBox()`
  of every `<text>` with every `<rect>` and with the other texts. `chrome-headless-shell
  --dump-dom` prints the result. The same page with `svg text { font-family: Verdana
  !important }` stands for a reader whose font is wider.

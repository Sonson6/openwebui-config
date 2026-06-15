---
name: plot
description: Render a data chart (bar, line, scatter, pie, histogram, box, heatmap, etc.) inline in chat with plot(), so the user can download it as a vector SVG (for Word/PowerPoint) or PNG. Use only when the user explicitly asks for a chart, plot, or graph of data. Do not use for diagrams, illustrations, general UI, or ordinary markdown/tables.
---

# Plotly Visualizer

This is the handbook for the `plot()` tool. It renders a **Plotly chart** inline in the chat from a declarative figure spec, and gives the user native **Download SVG** and **Download PNG** buttons (the camera icons in the chart's toolbar). The SVG is true vector and drops cleanly into Word / PowerPoint.

## When to use it

Call `plot()` **only** when the user clearly and explicitly asks to chart/plot/graph some data — "make a bar chart", "plot this as a line graph", "show me a pie chart of…", etc.

Do **not** use it for:
- Diagrams, flowcharts, illustrations, maps, or interactive UI → those are not Plotly charts.
- Plain data the user only wants as a table or in prose.
- Anything the user did not explicitly ask to see as a chart.

If the request is for a non-chart visual, this is the wrong tool.

## How to use

1. Call `plot(title="…", figure="…")`. **You must call the tool** — it mounts the chart in the chat.
2. `title` is a short label, also used for the download filename.
3. `figure` is a **JSON string** of a Plotly figure: an object with a `data` array of traces and an optional `layout` object.
4. The chart renders **complete and immediately** — there is no streaming, no delimiters, no follow-up block to emit.
5. After the tool returns, write prose describing **what the chart shows**. Do **not** re-print the JSON and do **not** describe the spec.

### The `figure` argument

It is exactly a Plotly figure: `{"data": [ ...traces... ], "layout": { ...optional... }}`.

Each trace is an object with a `type` and its data arrays. Minimal bar chart:

```json
{"data":[{"type":"bar","x":["India","China","USA"],"y":[1450,1409,345]}],
 "layout":{"title":{"text":"Top 3 — Population (millions)"},
           "xaxis":{"title":{"text":"Country"}},
           "yaxis":{"title":{"text":"Millions"}}}}
```

Pass this as a JSON **string** to `figure`. It must be valid JSON: use `null`/`true`/`false` (not Python `None`/`True`), no trailing commas, no comments. If the tool returns an `ERROR:` string, read it and retry with corrected JSON.

## What the tool handles for you — do NOT set these

The tool themes the chart to match the chat (light/dark) automatically. **Do not set** any of:
- `paper_bgcolor`, `plot_bgcolor` — backgrounds are themed (and made solid so exports stay legible).
- `layout.font.color`, axis `gridcolor` / `zerolinecolor` / `linecolor` — themed.
- A default `colorway` — a pleasant palette is applied. (You may still set per-trace `marker.color` when a specific color matters, e.g. semantic red/green.)

Setting them is harmless (your value wins) but usually makes the chart clash with the chat theme. Leave them out and let the tool theme it.

You **should** set, as needed: `layout.title.text`, `layout.xaxis.title.text` / `layout.yaxis.title.text`, `layout.barmode` (`"group"` / `"stack"`), trace `name` (legend label), `layout.height` (defaults to 460), and `hovertemplate` / `text` for labels.

## Export — automatic, nothing to do

Every rendered chart shows two camera buttons in its toolbar:
- **Download SVG** — vector; the right choice for pasting into Word / PowerPoint (Insert → Pictures → This Device).
- **Download PNG** — raster at 2× scale; for quick sharing or apps that don't accept SVG.

For Excel, an image isn't useful — if the user wants the *numbers*, give them the data as a table or CSV in your reply instead.

## Chart-type cookbook

All of these are passed as the `figure` JSON string. Only `data` differs; `layout` is optional.

**Grouped bar**
```json
{"data":[{"type":"bar","name":"2020","x":["A","B","C"],"y":[3,7,5]},
         {"type":"bar","name":"2024","x":["A","B","C"],"y":[4,6,8]}],
 "layout":{"barmode":"group"}}
```

**Line / multi-series**
```json
{"data":[{"type":"scatter","mode":"lines+markers","name":"Revenue","x":[2021,2022,2023,2024],"y":[12,18,15,24]},
         {"type":"scatter","mode":"lines","name":"Cost","x":[2021,2022,2023,2024],"y":[8,10,11,13]}],
 "layout":{"xaxis":{"title":{"text":"Year"}},"yaxis":{"title":{"text":"$M"}}}}
```

**Scatter**
```json
{"data":[{"type":"scatter","mode":"markers","x":[1,2,3,4,5],"y":[2,5,3,8,6],
          "marker":{"size":12}}]}
```

**Pie / donut**
```json
{"data":[{"type":"pie","labels":["A","B","C","D"],"values":[30,25,25,20],"hole":0.4}]}
```

**Histogram**
```json
{"data":[{"type":"histogram","x":[1,1,2,3,3,3,4,5,5,6,7]}]}
```

**Horizontal bar** — set `orientation` and swap x/y:
```json
{"data":[{"type":"bar","orientation":"h","y":["A","B","C"],"x":[12,7,19]}]}
```

**Box plot**
```json
{"data":[{"type":"box","name":"Group 1","y":[1,2,2,3,4,4,5,9]},
         {"type":"box","name":"Group 2","y":[2,3,3,4,5,5,6]}]}
```

**Heatmap**
```json
{"data":[{"type":"heatmap","z":[[1,20,30],[20,1,60],[30,60,1]],
          "x":["Mon","Tue","Wed"],"y":["Morning","Afternoon","Evening"]}]}
```

Other Plotly types work the same way: `bar`, `scatter`, `scattergl` (large point counts), `pie`, `histogram`, `histogram2d`, `box`, `violin`, `heatmap`, `contour`, `sunburst`, `treemap`, `funnel`, `waterfall`, `scatterpolar`, `scatter3d`, `surface`, `choropleth`, and more.

## Notes & limits

- **Requires "iframe Sandbox Allow Same Origin"** in Open WebUI Settings → Interface (needed for theme sync and the height/download bridges).
- **One chart per call.** For several charts, call `plot()` multiple times.
- Keep data reasonable — aggregate or sample very large series before plotting (there's a hard size cap on the figure spec).
- Don't request map/tile charts that fetch external tiles: the strict security level blocks outbound network. Plain `choropleth` (with built-in geometries) is fine; `scattermapbox`/tiles are not.

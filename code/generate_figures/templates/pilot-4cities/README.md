# pilot-4cities templates

This directory contains the templates for the three pilot-4cities pages in [`results/figures/interactive/pilot-4cities/`](../../../../results/figures/interactive/pilot-4cities/).
Each page reads its data from `window.PAGE_DATA`, which the build script embeds; the pages filter and draw but compute no results of their own beyond summaries of the points they plot.

## Contents

- [`approach.html`](approach.html): The approach walkthrough: design, sample map, chatbots, coding (with a worked example), geocoding, policy categories, accuracy rules, pipeline, limitations, glossary, and sources.
- [`explorer.html`](explorer.html): The response explorer: filters, search, the list of answers, the reading pane with highlight layers and citation markers, the three-chatbot comparison, and the coded details of each answer.
- [`brief.html`](brief.html): The data brief: the chart helpers (dot rows, jittered points with box plots, lines with a crosshair, scatter, map) and one tab per research question, each with its finding, figure, caption, and table of numbers.
- [`common.css`](common.css): Styles every page shares, with light and dark color tokens (the chatbots take the first three slots of the dataviz reference palette, which stay distinguishable under color-vision deficiency).
- [`common.js`](common.js): Helpers every page shares: chatbot names and colors, number formats, the theme button, the tooltip, legends, the US map projection and state labels, safe markdown rendering, and highlighting of copied text in rendered markdown.

## Other instructions

Rebuild after editing: `uv run python code/generate_figures/build_pilot_4cities_pages.py`.
To check a page in a browser without double-clicking, serve the output folder (for example `uv run python -m http.server` in it); the pages load nothing over the network either way.

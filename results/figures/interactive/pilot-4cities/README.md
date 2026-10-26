# pilot-4cities pages

This directory contains the three shareable pages for the pilot-4cities audit (591 answers from Claude, Gemini, and ChatGPT about 197 cities and towns, collected 2026-10-23).
Each page is one self-contained HTML file: its data, styles, and libraries are inlined, so it opens with a double-click, needs no server or internet connection, and can be emailed or shared as a single file.

## Contents

- [`pilot_4cities_approach.html`](pilot_4cities_approach.html): How the pilot was designed and run, for readers who do not code: the query, the city sample (with a map), the chatbots, how answers were coded (with a worked example), geocoding, state policy, how accuracy is judged, limitations, a glossary, and sources.
- [`pilot_4cities_explorer.html`](pilot_4cities_explorer.html): Every answer as the chatbot wrote it, filterable by state, place, chatbot, state policy, place size, and what the answer says, with full-text search, a side-by-side view of the three chatbots for one place, and optional highlighting of the coded places, resources, addresses, phone numbers, distance claims, state-law statements, crisis pregnancy centers, and cited websites by type. The URL keeps the selected answer and highlights, so a view can be shared.
- [`pilot_4cities_brief.html`](pilot_4cities_brief.html): A data brief with one tab per research question (what the chatbots recommend, how far they send people, where users in total-ban states are sent, whether the places are among the closest, whether answers describe state law correctly, whether stated distances are right, city size, agreement between chatbots, accompanying guidance, and websites shown), each with a D3 figure, a caption, and a table of the numbers.

## Other instructions

The pages are built files: change the templates in [`code/generate_figures/templates/pilot-4cities/`](../../../../code/generate_figures/templates/pilot-4cities/) and rebuild with [`code/generate_figures/build_pilot_4cities_pages.py`](../../../../code/generate_figures/build_pilot_4cities_pages.py).
Every coded result in these pages comes from AI agents and has not yet been checked by human coders; the pages say so.

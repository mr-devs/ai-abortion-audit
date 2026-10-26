# Templates

This directory contains the HTML templates and vendored JavaScript libraries that [`build_pilot_4cities_pages.py`](../build_pilot_4cities_pages.py) turns into self-contained pages.

## Contents

- [`pilot-4cities/`](pilot-4cities/): Templates for the three pilot-4cities pages and the styles and helpers they share.
- [`vendor/`](vendor/): Pinned, minified copies of the JavaScript libraries the pages inline, so the built pages work offline.

## Other instructions

A template marks where a shared file goes with `<!-- @inline path -->` (relative to this directory; a `.css` file becomes a `<style>` block and a `.js` file a `<script>` block) and where the page's data goes with `<!-- @data -->`.

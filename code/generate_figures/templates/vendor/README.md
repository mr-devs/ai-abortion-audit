# Vendor

This directory contains pinned, minified JavaScript libraries that the page templates inline, so the built pages work with no internet connection.
They were downloaded unmodified from cdnjs on 2026-10-25.

## Contents

- [`d3-7.9.0.min.js`](d3-7.9.0.min.js): D3 7.9.0 (ISC license), for charts and maps; from `https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js`.
- [`marked-12.0.2.min.js`](marked-12.0.2.min.js): marked 12.0.2 (MIT license), to render answers' markdown; from `https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js`.
- [`purify-3.1.6.min.js`](purify-3.1.6.min.js): DOMPurify 3.1.6 (Apache 2.0 or MPL 2.0), to sanitize rendered markdown; from `https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.1.6/purify.min.js`.

## Other instructions

To update a library, download the new version next to the old one, change the `<!-- @inline vendor/... -->` lines in the templates, and delete the old file.

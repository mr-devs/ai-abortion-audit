// Shared helpers for the pilot-4cities pages: chatbot names and colors,
// number formats, the theme button, one tooltip, legends, SVG setup, the
// US map projection, and safe markdown rendering. Every page reads its data
// from window.PAGE_DATA, which the build script embeds.
(function () {
  const D = window.PAGE_DATA;
  const PROVIDER_IDS = ["anthropic", "gemini", "openai"];
  const PROVIDER_VAR = { anthropic: "--claude", gemini: "--gemini", openai: "--chatgpt" };
  const byId = Object.fromEntries((D ? D.meta.providers : []).map((p) => [p.id, p]));

  const AA = {
    D,
    PROVIDER_IDS,
    provider: (id) => byId[id],
    label: (id) => (byId[id] ? byId[id].label : id),
    fullLabel: (id) => (byId[id] ? `${byId[id].label} (${byId[id].model_label})` : id),
    color: (id) => `var(${PROVIDER_VAR[id]})`,
  };

  // Number formats.
  AA.fmt = {
    int: (v) => (v == null || isNaN(v) ? "–" : Math.round(v).toLocaleString("en-US")),
    pct: (v, digits = 0) => (v == null || isNaN(v) ? "–" : `${(v * 100).toFixed(digits)}%`),
    dec: (v, digits = 1) => (v == null || isNaN(v) ? "–" : Number(v).toFixed(digits)),
    mi: (v) => {
      if (v == null || isNaN(v)) return "–";
      if (v < 10) return `${Number(v).toFixed(1)} mi`;
      return `${Math.round(v).toLocaleString("en-US")} mi`;
    },
    pop: (v) => Number(v).toLocaleString("en-US"),
  };

  // Guttmacher policy categories: rank 1-7, with total-ban states apart.
  AA.POLICY = [
    { key: "ban", label: "Total ban", var: "--pol-ban" },
    { key: "1", label: "Most restrictive (no total ban)", var: "--pol-1" },
    { key: "2", label: "Very restrictive", var: "--pol-2" },
    { key: "3", label: "Restrictive", var: "--pol-3" },
    { key: "4", label: "Some restrictions/protections", var: "--pol-4" },
    { key: "5", label: "Protective", var: "--pol-5" },
    { key: "6", label: "Very protective", var: "--pol-6" },
    { key: "7", label: "Most protective", var: "--pol-7" },
  ];
  AA.policyKey = (rank, totalBan) => (totalBan ? "ban" : String(rank));
  AA.policyColor = (rank, totalBan) =>
    `var(${AA.POLICY.find((p) => p.key === AA.policyKey(rank, totalBan)).var})`;
  AA.policyLabel = (rank, totalBan) => AA.POLICY.find((p) => p.key === AA.policyKey(rank, totalBan)).label;

  // Escape text for innerHTML.
  AA.esc = (s) =>
    String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  // Theme button: cycles auto -> light -> dark; remembered in this browser.
  AA.initTheme = function () {
    const KEY = "aa-theme";
    let mode = "auto";
    try { mode = localStorage.getItem(KEY) || "auto"; } catch (e) { /* storage blocked */ }
    const apply = () => {
      if (mode === "auto") document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme", mode);
      document.querySelectorAll(".theme-btn").forEach((b) => {
        b.textContent = { auto: "Theme: auto", light: "Theme: light", dark: "Theme: dark" }[mode];
      });
    };
    apply();
    document.querySelectorAll(".theme-btn").forEach((b) =>
      b.addEventListener("click", () => {
        mode = { auto: "light", light: "dark", dark: "auto" }[mode];
        try { localStorage.setItem(KEY, mode); } catch (e) { /* storage blocked */ }
        apply();
      })
    );
  };

  // One tooltip per page. show(event, title, lines[]) keeps it in the viewport.
  AA.tip = (function () {
    let el = null;
    const ensure = () => {
      if (!el) { el = document.createElement("div"); el.className = "tip"; document.body.appendChild(el); }
      return el;
    };
    return {
      show(event, title, lines = []) {
        const t = ensure();
        t.replaceChildren();
        const h = document.createElement("div"); h.className = "t"; h.textContent = title; t.appendChild(h);
        for (const line of lines) { const r = document.createElement("div"); r.className = "r"; r.textContent = line; t.appendChild(r); }
        t.classList.add("on");
        const pad = 14, w = t.offsetWidth, hgt = t.offsetHeight;
        let x = event.clientX + pad, y = event.clientY + pad;
        if (x + w > window.innerWidth - 8) x = event.clientX - pad - w;
        if (y + hgt > window.innerHeight - 8) y = event.clientY - pad - hgt;
        t.style.left = `${Math.max(8, x)}px`;
        t.style.top = `${Math.max(8, y)}px`;
      },
      hide() { if (el) el.classList.remove("on"); },
    };
  })();

  // Legend: items are [label, color, shape] with shape "dot", "sq", or "line".
  AA.legend = function (el, items) {
    el.replaceChildren();
    el.classList.add("legend");
    for (const [label, color, shape] of items) {
      const s = document.createElement("span");
      const i = document.createElement("i");
      if (shape === "ring" || shape === "outline") {
        // An open marker: a ring (circle) or an outlined square.
        i.style.background = "transparent";
        i.style.border = `1.5px solid ${color}`;
        if (shape === "outline") i.className = "sq";
      } else {
        if (shape && shape !== "dot") i.className = shape;
        i.style.background = color;
      }
      s.append(i, document.createTextNode(label));
      el.appendChild(s);
    }
  };
  AA.providerLegend = (el) => AA.legend(el, PROVIDER_IDS.map((p) => [AA.fullLabel(p), AA.color(p), "dot"]));

  // A fresh responsive SVG inside el, width from the element.
  AA.svg = function (el, height, minWidth = 300) {
    el.querySelectorAll("svg").forEach((n) => n.remove());
    const width = Math.max(minWidth, el.clientWidth || minWidth);
    const svg = d3.select(el).append("svg")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("width", "100%")
      .attr("role", "img");
    return { svg, width, height };
  };

  // Measure the widest of some labels, in SVG pixels.
  AA.textWidth = function (svg, labels, cls) {
    const t = svg.append("text").attr("class", cls || null);
    let w = 0;
    for (const s of labels) { t.text(s); w = Math.max(w, t.node().getComputedTextLength()); }
    t.remove();
    return w;
  };

  // Albers USA projection fitted to the state outlines.
  AA.usProjection = function (width, height, shapes) {
    const pad = 10;
    return d3.geoAlbersUsa().fitExtent([[pad, pad], [width - pad, height - pad]], shapes);
  };

  // Two-letter labels for every state on a US map. A label sits at the
  // center of the state's largest piece (so Michigan's is on the lower
  // peninsula); states too small to hold one get a label in the nearby ocean
  // with a short leader line. Labels have a halo so they read over lines.
  const LABEL_OFFSHORE = {
    VT: [-72.9, 45.5], NH: [-69.6, 43.4], MA: [-69.3, 41.9], RI: [-70.4, 40.9],
    CT: [-71.5, 40.2], NJ: [-73.2, 39.2], DE: [-73.8, 38.3], MD: [-74.4, 37.4], DC: [-75.0, 36.6],
  };
  AA.stateLabels = function (svg, proj, path, shapes, width) {
    const size = width < 560 ? 8.5 : width < 900 ? 9.5 : 10.5;
    const g = svg.append("g").style("pointer-events", "none");
    for (const f of shapes.features) {
      const abbr = f.properties.abbr;
      let shape = f;
      if (f.geometry.type === "MultiPolygon") {
        const parts = f.geometry.coordinates.map((c) => ({ type: "Polygon", coordinates: c }));
        shape = parts.reduce((a, b) => (d3.geoArea(b) > d3.geoArea(a) ? b : a));
      }
      const at = path.centroid(shape);
      if (!at || isNaN(at[0])) continue;
      let xy = at;
      if (LABEL_OFFSHORE[abbr]) {
        const off = proj(LABEL_OFFSHORE[abbr]);
        if (off) {
          g.append("line").attr("x1", at[0]).attr("y1", at[1]).attr("x2", off[0] - 2).attr("y2", off[1])
            .style("stroke", "var(--muted)").style("stroke-width", 0.7);
          xy = off;
        }
      }
      g.append("text").attr("x", xy[0]).attr("y", xy[1]).attr("dy", "0.35em")
        .attr("text-anchor", LABEL_OFFSHORE[abbr] ? "start" : "middle")
        .style("font-size", `${size}px`).style("font-weight", 600).style("fill", "var(--ink-2)")
        .style("stroke", "var(--surface)").style("stroke-width", 2.5).style("stroke-linejoin", "round").style("paint-order", "stroke")
        .text(abbr);
    }
  };

  // Markdown to safe HTML (marked + DOMPurify), links open in a new tab.
  AA.markdown = function (text) {
    // GFM reads a single "~" pair as strikethrough, but chatbots use "~" to
    // mean "about" ("~40 miles ... (~1 hour)"); escape lone tildes so they
    // show as written. "~~double~~" strikethrough is left alone.
    const safe = text.replace(/(^|[^~\\])~(?!~)/g, "$1\\~");
    const html = marked.parse(safe, { gfm: true, breaks: false });
    const clean = DOMPurify.sanitize(html, { ADD_ATTR: ["target"] });
    const wrap = document.createElement("div");
    wrap.innerHTML = clean;
    wrap.querySelectorAll("a").forEach((a) => { a.target = "_blank"; a.rel = "noopener noreferrer"; });
    return wrap;
  };

  // Highlighting copied text in rendered markdown.
  // The coded spans (names, addresses, quotes) were copied from the raw
  // markdown, so they may carry markdown syntax the rendered page does not
  // show. Both sides are normalized (markdown stripped, whitespace collapsed)
  // before matching; a match can span several DOM text nodes (e.g. across
  // bold text) and each piece is wrapped in a <mark>.
  AA.stripMarkdown = (s) =>
    String(s || "")
      .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/\*\*|__|`/g, "")
      .replace(/(^|\s)[*_](?=\S)|(?<=\S)[*_](?=\s|$)/g, "$1")
      .replace(/^[\s#>*\-|]+|[\s|]+$/g, "")
      .replace(/\s+/g, " ")
      .trim();

  function textIndex(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
      acceptNode: (n) => (n.nodeType === 1 && n.classList.contains("cite") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    const chars = [];
    const map = [];
    let prevSpace = true;
    let lastText = null;
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (n.nodeType === 1) {
        // A line break separates words just as a space does. It maps to the
        // end of the previous text node, which wrapping skips.
        if (n.tagName === "BR" && !prevSpace && lastText) {
          chars.push(" "); map.push([lastText, lastText.nodeValue.length]); prevSpace = true;
        }
        continue;
      }
      lastText = n;
      const s = n.nodeValue;
      for (let i = 0; i < s.length; i++) {
        const space = /\s/.test(s[i]);
        if (space && prevSpace) continue;
        chars.push(space ? " " : s[i]);
        map.push([n, i]);
        prevSpace = space;
      }
    }
    return { text: chars.join(""), map };
  }

  // Wrap every occurrence (or only the first) of needle in <mark class=cls>.
  // Returns the number of matches.
  AA.highlight = function (root, needle, cls, { all = true, data = null } = {}) {
    let target = AA.stripMarkdown(needle);
    if (target.length < 3) return 0;
    // Markdown that does not render (e.g. an unclosed "**") stays on the page
    // as written; fall back to the copied text with only whitespace collapsed.
    const plain = String(needle).replace(/\s+/g, " ").trim();
    if (plain !== target) {
      const page = textIndex(root).text;
      if (!page.includes(target) && !page.toLowerCase().includes(target.toLowerCase()) && page.includes(plain)) target = plain;
    }
    let count = 0;
    let from = 0;
    for (;;) {
      const idx = textIndex(root);
      let at = idx.text.indexOf(target, from);
      if (at < 0) at = idx.text.toLowerCase().indexOf(target.toLowerCase(), from);
      if (at < 0) break;
      const end = at + target.length; // exclusive
      // Group the matched characters by text node.
      const pieces = new Map();
      for (let k = at; k < end; k++) {
        const [node, off] = idx.map[k];
        if (off >= node.nodeValue.length) continue;
        const p = pieces.get(node) || [off, off];
        p[0] = Math.min(p[0], off); p[1] = Math.max(p[1], off);
        pieces.set(node, p);
      }
      for (const [node, [s, e]] of [...pieces.entries()].reverse()) {
        const mid = node.splitText(s);
        mid.splitText(e - s + 1);
        const mark = document.createElement("mark");
        mark.className = cls;
        if (data) for (const [k, v] of Object.entries(data)) mark.dataset[k] = v;
        mid.parentNode.insertBefore(mark, mid);
        mark.appendChild(mid);
      }
      count++;
      if (!all) break;
      from = at + 1; // indices shift by zero characters: marks add no text
    }
    return count;
  };

  // Remove every <mark> of the given classes (or all), restoring the text.
  AA.unhighlight = function (root, selector = "mark") {
    root.querySelectorAll(selector).forEach((m) => {
      const parent = m.parentNode;
      while (m.firstChild) parent.insertBefore(m.firstChild, m);
      parent.removeChild(m);
      parent.normalize();
    });
  };

  // Redraw on resize (debounced) and on theme change.
  AA.onResize = function (fn) {
    let timer = null;
    let lastW = window.innerWidth;
    window.addEventListener("resize", () => {
      if (window.innerWidth === lastW) return;
      lastW = window.innerWidth;
      clearTimeout(timer);
      timer = setTimeout(fn, 150);
    });
  };

  // Shown when the data or a library is missing.
  AA.failIfMissing = function () {
    if (window.PAGE_DATA && window.d3) return false;
    document.body.innerHTML = `<div class="load-error"><h2>This page could not load</h2>
      <p>The page's data or its drawing library is missing. Rebuild it with
      <code>uv run python code/generate_figures/build_pilot_4cities_pages.py</code>.</p></div>`;
    return true;
  };

  window.AA = AA;
})();

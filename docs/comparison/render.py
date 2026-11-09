"""Build comparison.html, a copy of the comparison page that opens in any browser.

    python docs/comparison/render.py

page.html reads its data through a small `dash` API. This script puts the CSV files
from data/ into the page, adds that API and a theme, so the result needs no server and
no network.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

STYLE = """
:root {
  --cds-gap-xs: 4px; --cds-gap-sm: 8px; --cds-gap-md: 12px; --cds-gap-lg: 16px; --cds-gap-xl: 28px;
  --cds-pad-xs: 4px; --cds-pad-sm: 8px; --cds-pad-md: 12px; --cds-pad-lg: 16px; --cds-radius: 6px;
  --cds-font-size-caption: 12px; --cds-font-size-body: 15px; --cds-font-size-heading: 19px; --cds-font-size-title: 30px;
  --cds-font-weight-medium: 600;
  --font-anthropic-sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-anthropic-serif: Georgia, "Times New Roman", serif;
  --color-bg: #fbfaf8; --color-panel: #ffffff; --color-fg: #1f1e1c; --color-fg-muted: #66635d;
  --color-border-line: #e2dfd8; --color-ok: #1a7f37; --color-warn: #9a6700; --color-bad: #c9302c;
  --cds-surface-popover: #ffffff; --cds-border: #d6d2c9; --cds-text-secondary: #66635d;
  --cds-shadow-popover: 0 4px 16px rgba(0, 0, 0, .12);
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a; --series-4: #eda100;
  --series-5: #e87ba4; --series-6: #008300; --series-7: #6250d6; --series-8: #e34948;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --color-bg: #1c1b1a; --color-panel: #262523; --color-fg: #ecebe8; --color-fg-muted: #a9a59d;
    --color-border-line: #3a3835; --color-ok: #4ac26b; --color-warn: #d4a72c; --color-bad: #f47067;
    --cds-surface-popover: #2e2d2a; --cds-border: #4a4743; --cds-text-secondary: #a9a59d;
    --cds-shadow-popover: 0 4px 16px rgba(0, 0, 0, .5);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
    --series-5: #d55181; --series-6: #008300; --series-7: #9085e9; --series-8: #e66767;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --color-bg: #1c1b1a; --color-panel: #262523; --color-fg: #ecebe8; --color-fg-muted: #a9a59d;
  --color-border-line: #3a3835; --color-ok: #4ac26b; --color-warn: #d4a72c; --color-bad: #f47067;
  --cds-surface-popover: #2e2d2a; --cds-border: #4a4743; --cds-text-secondary: #a9a59d;
  --cds-shadow-popover: 0 4px 16px rgba(0, 0, 0, .5);
  --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
  --series-5: #d55181; --series-6: #008300; --series-7: #9085e9; --series-8: #e66767;
  color-scheme: dark;
}
body { margin: 0; background: var(--color-bg); color: var(--color-fg); font-family: var(--font-anthropic-sans); }
#dash-root { max-width: 1200px; margin: 0 auto; padding: 24px 16px 48px; }
"""

# The page's data API: every dataset is a loaded table of text cells.
SHIM = r"""
(() => {
  const parseCsv = (text) => {
    const rows = [[]]; let field = '', quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (quoted) {
        if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
        else if (c === '"') quoted = false;
        else field += c;
      } else if (c === '"') quoted = true;
      else if (c === ',') { rows[rows.length - 1].push(field); field = ''; }
      else if (c === '\n' || c === '\r') {
        if (c === '\r' && text[i + 1] === '\n') i++;
        rows[rows.length - 1].push(field); field = ''; rows.push([]);
      } else field += c;
    }
    if (field !== '' || rows[rows.length - 1].length) rows[rows.length - 1].push(field);
    const [head, ...body] = rows.filter((r) => r.length && !(r.length === 1 && r[0] === ''));
    return { columns: head, data: body.map((r) => Object.fromEntries(head.map((h, j) => [h, r[j] ?? '']))) };
  };
  const store = {};
  const files = JSON.parse(document.getElementById('dash-data').textContent);
  for (const [id, text] of Object.entries(files)) {
    store[id] = { status: 'ok', meta: [], refreshing: false, ...parseCsv(text) };
  }
  window.d3 = {
    sum: (xs) => xs.reduce((a, b) => a + (Number(b) || 0), 0),
    format: (spec) => spec === ',' ? (x) => Number(x).toLocaleString('en-US')
      : spec === '.1%' ? (x) => `${(Number(x) * 100).toFixed(1)}%` : (x) => String(x),
  };
  window.dash = {
    colors: Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`),
    data: (id) => store[id] || { status: 'missing', data: [], columns: [], meta: [] },
    calc: (id, { inputs, fn }) => {
      store[id] = { status: 'ok', data: fn(...inputs.map((i) => store[i].data)), meta: [] };
    },
    draw: (name, fn) => document.querySelectorAll(`[data-draw="${name}"]`).forEach((el) => fn(el)),
    onData: (fn) => fn(),
    setLink: (name) => history.replaceState(null, '', `#${name}`),
    params: () => ({}), setParams() {}, resetParams() {}, refresh() {},
  };
})();
"""


def main():
    page = open(os.path.join(HERE, "page.html")).read()
    data = {
        name[:-4]: open(os.path.join(HERE, "data", name)).read()
        for name in sorted(os.listdir(os.path.join(HERE, "data")))
        if name.endswith(".csv")
    }
    payload = json.dumps(data).replace("</", "<\\/")
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ActiTraC Implementation Comparison</title>
<style>{STYLE}</style>
</head>
<body>
<!-- Built by docs/comparison/render.py from page.html and data/. Edit those, not this file. -->
<script type="application/json" id="dash-data">{payload}</script>
<script>{SHIM}</script>
<div id="dash-root">
{page}
</div>
</body>
</html>
"""
    with open(os.path.join(HERE, "comparison.html"), "w") as file:
        file.write(html)
    print(f"comparison.html, {len(html)} bytes, {len(data)} datasets")


if __name__ == "__main__":
    main()

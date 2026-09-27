# Vendored front-end assets

Every script, stylesheet and font the console serves comes from the console itself
(SE-09). No CDN: the page loads no third-party code, works with no internet, and
the Content-Security-Policy can be `default-src 'self'` with nothing else allowed.

Downloaded once from the npm registry, on 2026-09-27, and committed. To update
one, fetch the new version, replace the file, update its line here, and run the
suite — a page test asserts that no page references an external host.

## Versions

| Library | Version | Files | What uses it |
|---|---|---|---|
| htmx | 2.0.11 | `static/vendor/htmx/htmx.min.js` | every partial swap and poll |
| htmx SSE extension | 2.2.4 | `static/vendor/htmx/htmx-ext-sse.js` | loaded for the job stream that arrives with B2 |
| Alpine.js | 3.17.4 | `static/vendor/alpine/alpine.min.js` | small in-page interactions |
| Shoelace | 2.20.1 | `static/vendor/shoelace/cdn/` | tabs, details, dialogs, chips, tooltips, alerts, breadcrumbs, copy buttons |

## Checksums

```
d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717  htmx/htmx.min.js
3b5992a541619babefc4c169505af474df5c3039da51e59b96ccf9241ecd61d2  htmx/htmx-ext-sse.js
232519394c6c8fdba6f362b1d9da16106db513cdbf899011f00daab4051df31c  alpine/alpine.min.js
d5bdcd030d02204710e478da9c576fb0543460509709348691af4dc2b378da9c  shoelace/cdn/shoelace-autoloader.js
48932bd11b44ee99ce1ebe8c7fe2fc9337119f026807edfb7aca9a212ff22d36  shoelace/cdn/themes/light.css
```

## What was trimmed from Shoelace, and why

Shoelace's distribution is 13 MB and 2545 files, most of it an icon set and
editor metadata that no browser requests. What is served:

- `cdn/shoelace-autoloader.js` and `cdn/chunks/` — the autoloader and the
  component chunks it lazily fetches from beside itself. The whole `chunks`
  folder is kept: the components share code through it, and guessing which
  chunks a component needs is how a dialog stops opening.
- `cdn/components/` and `cdn/themes/light.css` — the components and the theme.
- `cdn/translations/` — kept; the autoloader reads them.
- `cdn/assets/icons/` — **trimmed from 2052 SVGs to the 57 the templates name.**
  The icons Shoelace's own components use internally (a select's chevron, an
  alert's close button) come from its "system" library inside `chunks/`, not from
  this folder, so trimming it does not affect them. Adding an `<sl-icon
  name="…">` to a template means copying that SVG in — a missing one renders as
  empty space, not as an error.
- Removed: `cdn/react/` (wrappers for a framework this console does not use),
  every `*.d.ts` and `*.map`, and `custom-elements.json`, `web-types.json` and
  `vscode.html-custom-data.json` (editor metadata, 1.1 MB).

The result is 3.5 MB and 547 files.

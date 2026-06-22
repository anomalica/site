# Architecture diagram assets

`pipeline.mmd` is the source of the data-flow diagram. `pipeline.svg` is a
**pre-rendered** static copy embedded by `layouts/_default/architecture.html`,
so the page loads no runtime Mermaid from a third-party CDN (keeps the privacy
policy's "no other third-party services" claim true).

The node click handlers (which drive the side panel) are re-bound in the
template from each node's id (`<prefix>-flowchart-<nodeId>-<n>`), so the static
SVG stays interactive.

## Regenerating after editing pipeline.mmd

The diagram needs a browser to render (Mermaid has no pure-Node renderer). With
a Chromium/Brave running with a remote debugging port (e.g. on `:9222`), render
`pipeline.mmd` through Mermaid 11 with these settings and save the resulting
`<svg>` as `pipeline.svg`:

- `theme: "base"`, `securityLevel: "loose"`
- `flowchart: { curve: "basis", nodeSpacing: 44, rankSpacing: 58, padding: 14, useMaxWidth: false }`
- `themeVariables: { fontFamily: "Outfit, sans-serif", fontSize: "17px", lineColor: "#5E5A50", edgeLabelBackground: "#F8F6F1" }`
- render id (svg prefix): `al`

The `.arch` widget is always light-themed, so only one (light) SVG is needed.

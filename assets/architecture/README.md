# Architecture diagram assets

The diagram **source** is the meta-repo's `anomalica/reference/pipeline.mmd`
(single source, alongside `reference/architecture.yaml` which feeds the detail
panels). `pipeline.svg` here is a **pre-rendered** static copy of it, embedded by
`layouts/_default/architecture.html` so the page loads no runtime Mermaid from a
third-party CDN (keeps the privacy policy's "no other third-party services" claim
true). The `.svg` is the only diagram file kept in this repo; do not add a local
`.mmd` copy - edit it at source in the meta-repo.

The node click handlers (which drive the side panel) are re-bound in the template
from each node's id (`<prefix>-flowchart-<nodeId>-<n>`), so the static SVG stays
interactive.

## Regenerating after the meta-repo's pipeline.mmd changes

Mermaid has no pure-Node renderer, so it needs a browser. With Brave running on a
remote debugging port (`:9222`), render the meta-repo's `reference/pipeline.mmd`
through Mermaid 11 and save the resulting `<svg>` over `pipeline.svg`. Outfit must
be loaded in the render page first (`document.fonts.ready`) or node widths come out
wrong and labels clip. Settings:

- `theme: "base"`, `securityLevel: "loose"`
- `flowchart: { curve: "basis", nodeSpacing: 44, rankSpacing: 58, padding: 14, useMaxWidth: false }`
- `themeVariables: { fontFamily: "Outfit, sans-serif", fontSize: "17px", lineColor: "#5E5A50", edgeLabelBackground: "#F8F6F1" }`
- render id (svg prefix): `al`

The `.arch` widget is always light-themed, so only one (light) SVG is needed.

The deploy refuses to publish a diagram that has drifted from the source: it
compares node ids, node labels and edge labels, so re-rendering after a source
change is not optional and forgetting it fails the deploy rather than shipping
quietly. It reports only - rendering needs a browser with the font loaded, and a
silent re-render at deploy time is how a clipped diagram ships without anyone
looking at it. Look at the result before you deploy.

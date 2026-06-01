# site

Static website for [Anomalica](https://anomalica.is), built with Hugo.

Presents the Anomalica knowledge graph as a browsable reference platform
for anomalous phenomena. Content is assembled upstream by the
[assembler](https://github.com/anomalica/assembler)
and rendered here as static HTML.

- Hugo static site generator
- Tailwind CSS v4
- 30-language support
- Dark mode

## Content boundary

This repository contains only templates, styling, and build configuration.
All content lives in
[content](https://github.com/anomalica/content) and is
pulled in via Hugo module mounts at build time:

- `content/pages/` mounts to `content/` (informational pages: about, methodology, etc.)
- `content/legal/` mounts to `content/legal/` (privacy, terms, licence)

Do not add content pages to this repository. New pages go in content.

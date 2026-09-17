# Anomalica site

The shared instructions in `/home/mark/repos/anomalica/AGENTS.md` apply. If they are not already in the current context, read that file before working here.

This repository owns the public Hugo site's templates, styling, build configuration and deployment checks. Reader-facing content is produced upstream in `/home/mark/repos/anomalica/content/`; do not add or hand-correct assembled content here.

## Development

```bash
just serve
just build
just deploy-check
```

- `just serve` runs Tailwind and Hugo at `http://localhost:1313/en/`.
- `just build` regenerates vendored assets and the JSON brief mirror before producing the production site.
- Verify interface changes in a browser at desktop and mobile widths as well as with a production build.

## Site boundaries

- Treat files mounted from sibling repositories in `hugo.toml` as externally owned sources of truth. Fix their producer rather than copying or manually repairing their output here.
- Keep URL moves and removals in `data/redirects.yaml`. Do not bypass the deploy removal guard without a durable retirement record and an explicit reason.
- Use `just deploy-check` to inspect production changes without publishing. A real deploy updates the public site and must retain all deploy safeguards.

# List available recipes
default:
    @just --list

# Run the site locally (Tailwind watch + Hugo server) at http://localhost:1313/en/
serve:
    npm run dev

# Production build into ./public (minified CSS + Hugo)
build:
    npm run build

# Build, verify and publish to the bunny zone behind anomalica.is, then purge
deploy:
    ./scripts/deploy.py

# Build and verify only - reports what a deploy would upload, delete and strip
deploy-check:
    ./scripts/deploy.py --dry-run

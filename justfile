# List available recipes
default:
    @just --list

# Run the site locally (Tailwind watch + Hugo server) at http://localhost:1313/en/
serve:
    npm run dev

# Production build into ./public (minified CSS + Hugo)
build:
    npm run build

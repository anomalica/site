# Hugoplate script.html partial requires lazy JS entries

The theme's `themes/hugoplate/layouts/_partials/essentials/script.html` calls
`resources.Concat` on the lazy scripts slice unconditionally. If no lazy JS
plugins are configured in `hugo.toml`, the build fails with:

    expected slice of Resource objects, received []interface {} instead

The fix is to override the partial in `layouts/_partials/essentials/script.html`
and guard the lazy concat with `{{ if $scriptsLazy }}`.

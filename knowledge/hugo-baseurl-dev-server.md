# Hugo baseURL must be "/" for dev server compatibility

Hugo generates absolute URLs from `baseURL` in `hugo.toml`. If set to
`https://anomalica.is/`, the dev server still generates links pointing
to that domain, causing all CSS, JS, and images to fail loading on
localhost.

Setting `baseURL = "/"` makes Hugo generate relative URLs, which work
in both development and production. The actual domain is set at the CDN
level (bunny.net) rather than in Hugo's config.

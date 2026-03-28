# Hugoplate images module cannot handle SVG favicons

The `gethugothemes/hugo-modules/images` favicon partial calls `.Resize` on the
favicon resource, which fails for SVG images with:

    this method is only available for raster images

The fix is to override `layouts/partials/favicon.html` and check for SVG with
`{{ if eq $res.MediaType.SubType "svg" }}` before attempting resize operations.
For SVG, emit a simple `<link rel="icon" type="image/svg+xml">` tag instead.

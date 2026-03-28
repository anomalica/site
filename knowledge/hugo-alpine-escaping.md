# Hugo escapes Alpine.js expressions in HTML attributes

Hugo's template engine escapes `<` characters in HTML attributes. If you
put an Alpine.js expression like `x-init="darkMode = val < 5"` on an
element, Hugo will escape the `<` to `&lt;` and break the JavaScript.

Also, Hugo injects its livereload script tag into the first element it
finds with attributes, which can land in the middle of a multi-line
x-init expression and break it.

The fix is to avoid complex Alpine expressions in HTML attributes.
Instead:
- Use an inline `<script>` for initialisation logic
- Put x-data and x-effect on `<body>` rather than `<html>`
- Keep Alpine attribute expressions simple (no comparison operators)

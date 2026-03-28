# Why Hugoplate didn't work for Anomalica

Hugoplate is a general-purpose Hugo starter with a marketing site layout.
It was chosen for its Tailwind CSS v4 integration and i18n plumbing, but
the cost of adapting it exceeded the cost of building from scratch.

Problems encountered:
- theme.json colour system maps to 8 abstract slots (primary, body, border,
  light, dark, text, text_dark, text_light). The Anomalica palette needs
  ~15 distinct colours with specific semantic roles. Every colour choice
  required fighting the abstraction.
- script.html crashes on empty lazy JS plugin list (needed override)
- favicon.html can't handle SVG (needed override)
- main.js references removed Swiper plugin (needed override)
- Layout assumes marketing site structure (hero + features + testimonials
  + call to action) rather than reference/encyclopaedia structure
- Hugo module dependencies pull in ~20 modules (adsense, cookie consent,
  gallery slider, etc.) that are all irrelevant

For a project with a strong existing design system (the brand board),
starting from Hugo + Tailwind CSS v4 without a theme is faster.
Tailwind v4 can be integrated directly via its CLI without needing
Hugoplate's wrapper scripts.

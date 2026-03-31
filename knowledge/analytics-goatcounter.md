# Analytics: GoatCounter

See ADR 0015 in the meta-repository for the full decision rationale.

## Implementation

GoatCounter will be self-hosted on EU infrastructure. When ready to deploy, add one of these to `layouts/_default/baseof.html` before the closing `</body>` tag:

**Script-based (recommended):**
```html
<script data-goatcounter="https://INSTANCE.goatcounter.com/count"
        async src="//INSTANCE.goatcounter.com/count.js"></script>
```

**No-JavaScript tracking pixel fallback:**
```html
<noscript><img src="https://INSTANCE.goatcounter.com/count?p=/PAGEPATH"></noscript>
```

Replace `INSTANCE` with the GoatCounter instance hostname.

## Pipeline integration

GoatCounter stores data in SQLite when self-hosted. The assembly pipeline can:

1. Query the REST API (bearer token authentication, 4 requests/second rate limit)
2. Use cursor-based export for incremental syncing (`last_hit_id` pagination)
3. Read the SQLite database directly if co-located

Output a `data/popular.json` for Hugo to consume when surfacing popular articles on the homepage.

## API reference

- Documentation: https://www.goatcounter.com/help/api
- API specification: https://www.goatcounter.com/api.html

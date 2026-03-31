# Colour System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate Anomalica's colour system from ad hoc brand-* tokens to a systematic four-slot pattern with primary, accent, and feedback colours.

**Architecture:** All changes are in two files: `assets/css/main.css` (token definitions and component classes) and the layout templates (class name updates). The CSS file is modified first to define both old and new tokens simultaneously, then templates are updated, then old tokens are removed.

**Tech Stack:** Tailwind CSS v4 with `@theme` directive, CSS custom properties, Hugo templates.

**Spec:** `knowledge/colour-system-design.md`

---

### Task 1: Add new semantic tokens to main.css

**Files:**
- Modify: `assets/css/main.css`

This task adds all new tokens alongside the existing ones. Both old (`brand-*`) and new (`primary-*`) names will coexist temporarily so nothing breaks mid-migration.

- [ ] **Step 1: Add new semantic token registrations to @theme block**

In `assets/css/main.css`, add these lines inside the `@theme { }` block, after the existing `--color-brand-subtle` line (line 43):

```css
  --color-on-primary: var(--on-primary);
  --color-primary-container: var(--primary-container);
  --color-on-primary-container: var(--on-primary-container);
  --color-primary-muted: var(--primary-muted);
  --color-primary-hover: var(--primary-hover);
  --color-accent: var(--accent);
  --color-on-accent: var(--on-accent);
  --color-accent-container: var(--accent-container);
  --color-on-accent-container: var(--on-accent-container);
  --color-accent-hover: var(--accent-hover);
  --color-error: var(--error);
  --color-on-error: var(--on-error);
  --color-error-container: var(--error-container);
  --color-on-error-container: var(--on-error-container);
  --color-warning: var(--warning);
  --color-on-warning: var(--on-warning);
  --color-warning-container: var(--warning-container);
  --color-on-warning-container: var(--on-warning-container);
  --color-success: var(--success);
  --color-on-success: var(--on-success);
  --color-success-container: var(--success-container);
  --color-on-success-container: var(--on-success-container);
```

- [ ] **Step 2: Add new CSS variable values to :root (light mode)**

In `:root { }` (around line 66), add after the existing `--brand-subtle` line:

```css
  --on-primary: #FFFFFF;
  --primary-container: #D1F1F1;
  --on-primary-container: #064D4D;
  --primary-muted: #72D3D3;
  --primary-hover: #085E5E;

  --accent: #B35A28;
  --on-accent: #FFFFFF;
  --accent-container: #F5E0CC;
  --on-accent-container: #7A3E1A;
  --accent-hover: #9A4D22;

  --error: #B83230;
  --on-error: #FFFFFF;
  --error-container: #FDEAEA;
  --on-error-container: #7A1F1E;

  --warning: #D49F3D;
  --on-warning: #FFFFFF;
  --warning-container: #FDF3E0;
  --on-warning-container: #7A5A1A;

  --success: #2D7D46;
  --on-success: #FFFFFF;
  --success-container: #E6F4EA;
  --on-success-container: #1A5C2E;
```

- [ ] **Step 3: Add new CSS variable values to .dark (dark mode)**

In `.dark { }` (around line 92), add after the existing `--brand-subtle` line:

```css
  --on-primary: #141413;
  --primary-container: #1E2422;
  --on-primary-container: #4BB8B8;
  --primary-muted: #085E5E;
  --primary-hover: #72D3D3;

  --accent: #E8A878;
  --on-accent: #1E1D19;
  --accent-container: #2A1E15;
  --on-accent-container: #E8A878;
  --accent-hover: #F0BD96;

  --error: #E57373;
  --on-error: #1E1D19;
  --error-container: #2C1A1A;
  --on-error-container: #E57373;

  --warning: #F0C86A;
  --on-warning: #1E1D19;
  --warning-container: #2A2214;
  --on-warning-container: #F0C86A;

  --success: #6ABF82;
  --on-success: #1E1D19;
  --success-container: #1A2A1E;
  --on-success-container: #6ABF82;
```

- [ ] **Step 4: Rebuild Tailwind and verify Hugo serves without errors**

```bash
npx @tailwindcss/cli -i assets/css/main.css -o assets/css/compiled.css
hugo server -D --port 1313
```

Open http://localhost:1313/ and confirm the site loads without visual changes (nothing should change yet since templates still use old names).

- [ ] **Step 5: Commit**

```bash
git add assets/css/main.css assets/css/compiled.css
git commit -m "feat: add primary, accent, and feedback colour tokens"
```

---

### Task 2: Rename brand-* to primary-* in @theme registrations

**Files:**
- Modify: `assets/css/main.css`

This task renames the Tailwind `@theme` registrations so utility classes like `bg-primary` and `text-primary` are generated. The old `--color-brand` registrations are removed. The underlying CSS variables (`--brand`, `--brand-hover`, etc.) remain temporarily as aliases.

- [ ] **Step 1: Replace brand registrations with primary registrations in @theme**

In the `@theme { }` block, replace these four lines:

```css
  --color-brand: var(--brand);
  --color-brand-hover: var(--brand-hover);
  --color-brand-muted: var(--brand-muted);
  --color-brand-subtle: var(--brand-subtle);
```

With:

```css
  --color-primary: var(--primary);
```

Note: `--color-on-primary`, `--color-primary-container`, `--color-on-primary-container`, `--color-primary-muted`, and `--color-primary-hover` were already added in Task 1.

- [ ] **Step 2: Add primary alias variables to :root**

In `:root { }`, add these aliases so the new `--primary` variable resolves correctly. Place them above the existing `--brand` line:

```css
  --primary: #0B6E6E;
```

This duplicates the `--brand` value. The old `--brand` variable stays for now (component classes still reference it).

- [ ] **Step 3: Add primary alias variable to .dark**

In `.dark { }`, add:

```css
  --primary: #4BB8B8;
```

- [ ] **Step 4: Rebuild Tailwind**

```bash
npx @tailwindcss/cli -i assets/css/main.css -o assets/css/compiled.css
```

- [ ] **Step 5: Commit**

```bash
git add assets/css/main.css assets/css/compiled.css
git commit -m "refactor: register primary-* tokens in Tailwind theme"
```

---

### Task 3: Update all template references from brand to primary

**Files:**
- Modify: `layouts/index.html`
- Modify: `layouts/_default/single.html`
- Modify: `layouts/_default/list.html`
- Modify: `layouts/partials/header.html`
- Modify: `layouts/partials/language-modal.html`

Every `text-brand`, `bg-brand`, `border-brand`, `bg-brand-subtle`, `bg-brand-muted`, `hover:text-brand`, and `hover:border-brand` in templates becomes the primary-* equivalent.

- [ ] **Step 1: Update layouts/index.html**

Find and replace all brand references:

| Find | Replace |
|------|---------|
| `text-brand` | `text-primary` |
| `bg-brand-muted` | `bg-primary-muted` |
| `hover:border-brand` | `hover:border-primary` |
| `hover:text-brand` | `hover:text-primary` |

Specific lines:
- Line 5: `text-brand` to `text-primary`
- Line 11: `bg-brand-muted` to `bg-primary-muted`
- Line 31: `hover:border-brand` to `hover:border-primary`
- Line 32: `text-on-surface group-hover:text-brand` to `text-on-surface group-hover:text-primary`
- Line 54: `text-brand` to `text-primary`

- [ ] **Step 2: Update layouts/_default/single.html**

- Line 27: `border-brand` to `border-primary`

- [ ] **Step 3: Update layouts/_default/list.html**

- Line 16: `hover:border-brand` to `hover:border-primary`
- Line 17: `group-hover:text-brand` to `group-hover:text-primary`

- [ ] **Step 4: Update layouts/partials/header.html**

- Line 19: `hover:text-brand` to `hover:text-primary`
- Line 40: `text-brand` to `text-primary`
- Line 41: `hover:text-brand` to `hover:text-primary`

- [ ] **Step 5: Update layouts/partials/language-modal.html**

- Line 33: `hover:border-brand` to `hover:border-primary`, `border-brand bg-brand-subtle` to `border-primary bg-primary-container`
- Line 34: `text-brand` (two occurrences) to `text-primary`, `group-hover:text-brand` to `group-hover:text-primary`

- [ ] **Step 6: Rebuild Tailwind and visually verify**

```bash
npx @tailwindcss/cli -i assets/css/main.css -o assets/css/compiled.css
```

Open http://localhost:1313/ and confirm the site looks identical to before. Check both light and dark mode. Check an article page (`/people/david-fravor/`), a list page (`/people/`), and the language modal.

- [ ] **Step 7: Commit**

```bash
git add layouts/ assets/css/compiled.css
git commit -m "refactor: rename brand to primary across all templates"
```

---

### Task 4: Update component classes in main.css from brand to primary

**Files:**
- Modify: `assets/css/main.css`

The `.section-label`, `.content`, `.tag-teal`, `.btn-primary`, and `.btn-secondary` classes all reference `var(--color-brand*)`. These need updating to `var(--color-primary*)`.

- [ ] **Step 1: Update .section-label**

Change line 200:
```css
  color: var(--color-brand);
```
To:
```css
  color: var(--color-primary);
```

- [ ] **Step 2: Update .content link styles**

Change lines 179-188:
```css
.content a {
  color: var(--color-primary);
  text-decoration: underline;
  text-underline-offset: 3px;
  text-decoration-color: var(--color-primary-muted);
  transition: color 0.15s ease, text-decoration-color 0.15s ease;
}

.content a:hover {
  color: var(--color-primary-hover);
  text-decoration-color: var(--color-primary);
}
```

- [ ] **Step 3: Update .tag-teal**

Change to use primary-container tokens:
```css
.tag-teal {
  background: var(--color-primary-container);
  color: var(--color-on-primary-container);
}

.dark .tag-teal {
  box-shadow: inset 0 0 0 1px var(--color-primary-muted);
}
```

- [ ] **Step 4: Update .tag-copper to use accent tokens**

Replace the existing `.tag-copper` block with:
```css
.tag-copper {
  background: var(--color-accent-container);
  color: var(--color-on-accent-container);
}

.dark .tag-copper {
  box-shadow: inset 0 0 0 1px var(--color-accent);
}
```

This removes the hardcoded hex values (`#F5E0CC`, `#7A3E1A`, `#2A2118`) and uses semantic tokens instead.

- [ ] **Step 5: Update .btn-primary and .btn-secondary**

Replace the button classes with:
```css
.btn-primary {
  background: var(--color-primary);
  color: var(--color-on-primary);
}

.btn-primary:hover {
  background: var(--color-primary-hover);
}

.btn-secondary {
  background: transparent;
  color: var(--color-primary);
  box-shadow: inset 0 0 0 1.5px var(--color-primary);
}

.btn-secondary:hover {
  background: var(--color-primary-container);
}
```

Remove the `.dark .btn-primary` block (the `on-primary` token already handles dark mode text colour).

- [ ] **Step 6: Rebuild Tailwind and visually verify**

```bash
npx @tailwindcss/cli -i assets/css/main.css -o assets/css/compiled.css
```

Check the site in both modes. The `.section-label` and `.content a` styles should look identical. Tags won't be visible yet (they use template classes) but the CSS is ready.

- [ ] **Step 7: Commit**

```bash
git add assets/css/main.css assets/css/compiled.css
git commit -m "refactor: update component classes to use primary/accent tokens"
```

---

### Task 5: Remove old brand-* variables and clean up dead weight

**Files:**
- Modify: `assets/css/main.css`

Now that all templates and component classes use primary-*, remove the old brand-* CSS variables and the unused `--color-amber` token.

- [ ] **Step 1: Remove old brand variables from :root**

Delete these lines from `:root { }`:
```css
  --brand: #0B6E6E;
  --brand-hover: #085E5E;
  --brand-muted: #72D3D3;
  --brand-subtle: #D1F1F1;
```

The `--primary`, `--primary-hover`, `--primary-muted`, and `--primary-container` variables (added in Tasks 1-2) already hold these same values.

- [ ] **Step 2: Remove old brand variables from .dark**

Delete these lines from `.dark { }`:
```css
  --brand: #4BB8B8;
  --brand-hover: #72D3D3;
  --brand-muted: #085E5E;
  --brand-subtle: #1E2422;
```

- [ ] **Step 3: Remove --color-amber from @theme**

Delete this line from `@theme { }`:
```css
  --color-amber: #D49F3D;
```

Amber's value now lives as the `--warning` token.

- [ ] **Step 4: Verify no references to old names remain**

```bash
grep -rn 'color-brand\|--brand' assets/css/main.css
grep -rn 'brand' layouts/
```

Both should return zero results. If any remain, update them.

- [ ] **Step 5: Rebuild Tailwind and do a full visual check**

```bash
npx @tailwindcss/cli -i assets/css/main.css -o assets/css/compiled.css
```

Check all pages in both modes:
- Homepage: http://localhost:1313/
- Article: http://localhost:1313/people/david-fravor/
- List: http://localhost:1313/people/
- Language modal (click the language button in header)

Everything should look identical to the pre-migration state.

- [ ] **Step 6: Commit**

```bash
git add assets/css/main.css assets/css/compiled.css
git commit -m "chore: remove old brand-* variables and unused amber token"
```

---

### Task 6: Update heading base styles to use semantic tokens

**Files:**
- Modify: `assets/css/main.css`

The heading styles currently use hardcoded `var(--color-ink)` and `#FFFFFF`. Update them to use semantic tokens.

- [ ] **Step 1: Update heading colour to use on-surface**

In the `@layer base { }` block, change:
```css
  h1, h2, h3, h4, h5, h6 {
    font-family: var(--font-content);
    font-weight: 600;
    line-height: 1.2;
    color: var(--color-ink);
  }

  .dark h1, .dark h2, .dark h3, .dark h4, .dark h5, .dark h6 {
    color: #FFFFFF;
  }
```

To:
```css
  h1, h2, h3, h4, h5, h6 {
    font-family: var(--font-content);
    font-weight: 600;
    line-height: 1.2;
    color: var(--color-on-surface);
  }
```

The `.dark` override is no longer needed because `--color-on-surface` already resolves to `#C8C4BC` in dark mode via the semantic token system.

Note: this changes dark mode headings from pure white (#FFFFFF) to the on-surface dark value (#C8C4BC). This is more consistent with the token system. If pure white headings are preferred in dark mode, a `--color-on-surface-heading` token could be added later, but the current on-surface value provides good contrast and softer reading.

- [ ] **Step 2: Rebuild and verify headings in both modes**

```bash
npx @tailwindcss/cli -i assets/css/main.css -o assets/css/compiled.css
```

Check that headings are readable on all pages in both modes. The article page title and browse card headings are the most visible.

- [ ] **Step 3: Commit**

```bash
git add assets/css/main.css assets/css/compiled.css
git commit -m "refactor: heading colours use on-surface semantic token"
```

---

### Task 7: Rebuild compiled CSS and final verification

**Files:**
- Modify: `assets/css/compiled.css` (generated)

- [ ] **Step 1: Clean rebuild of Tailwind**

```bash
npx @tailwindcss/cli -i assets/css/main.css -o assets/css/compiled.css --minify
```

- [ ] **Step 2: Full visual regression check**

Verify every page type in both light and dark mode:

1. Homepage (http://localhost:1313/) - hero, browse cards, principles, status, footer
2. Article (http://localhost:1313/people/david-fravor/) - section label, title, tags, content links, references
3. List (http://localhost:1313/people/) - section label, title, cards with tags
4. Language modal - open via header button, check border highlighting on English

Confirm:
- All teal elements render correctly (links, labels, tags, borders)
- Section labels say "PEOPLE", "BROWSE", "PRINCIPLES" in teal
- Tags have correct background/text colours
- Content links are teal with underlines
- Footer headings, links, and language bar are unchanged
- No visual regressions in either mode

- [ ] **Step 3: Verify new token classes exist in compiled output**

```bash
grep 'primary' assets/css/compiled.css | head -5
grep 'accent' assets/css/compiled.css | head -5
grep 'error' assets/css/compiled.css | head -5
```

Confirm that `bg-primary`, `text-accent`, `bg-error-container` etc. appear in the compiled CSS (they may not all be present if hugo_stats.json hasn't registered them yet - that's fine, they'll be generated when first used in templates).

- [ ] **Step 4: Commit final compiled CSS**

```bash
git add assets/css/compiled.css
git commit -m "chore: rebuild compiled CSS with complete colour token system"
```

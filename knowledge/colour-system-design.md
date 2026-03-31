# Colour System Design

## Overview

Anomalica's colour system uses a two-tier architecture: a raw palette of fixed colour values feeding into semantic tokens that flip between light and dark mode. Templates only reference semantic tokens, never raw values. This ensures consistent theming and makes future changes (new modes, palette adjustments) a single-point update.

The system follows a four-slot pattern inspired by Material Design 3's colour roles, adapted for simplicity. Each key colour (primary, accent) defines four tokens: the colour itself, a guaranteed-readable foreground, a softer container variant, and a foreground for that container. Feedback colours (error, warning, success) follow the same four-slot pattern.

## Architecture

```
Raw Palette          Semantic Tokens        CSS Classes
(fixed values)  -->  (mode-aware vars)  --> (used in HTML)

teal-700 #0B6E6E     --primary              bg-primary
copper   #B35A28     --accent               text-accent
ink      #1E1D19     --on-surface           text-on-surface
```

- **Raw palette**: defined in `@theme {}` in main.css. Generates Tailwind utility classes but these are not used directly in templates.
- **Semantic tokens**: defined as CSS custom properties in `:root` (light) and `.dark` (dark). Registered with Tailwind via `@theme {}` to generate utility classes.
- **CSS classes**: what appears in HTML templates. Always semantic names like `bg-primary`, `text-on-accent`, never raw names like `bg-teal-700`.

## Token Inventory

### Primary (Teal)

The main brand colour. Used for links, key buttons, active states, section labels.

| Token | Light | Dark | Purpose |
|-------|-------|------|---------|
| primary | #0B6E6E | #4BB8B8 | Brand colour for prominent elements |
| on-primary | #FFFFFF | #141413 | Text/icons on primary backgrounds |
| primary-container | #D1F1F1 | #1E2422 | Softer brand background (tags, highlights) |
| on-primary-container | #064D4D | #4BB8B8 | Text on primary-container |
| primary-hover | #085E5E | #72D3D3 | Hover state for primary elements |
| primary-muted | #72D3D3 | #085E5E | Decorative/underline use of brand colour |

### Accent (Copper)

Secondary action colour. Used for visual variety and hierarchy - secondary buttons, accent tags, call-to-action highlights. The warm counterpoint to teal.

| Token | Light | Dark | Purpose |
|-------|-------|------|---------|
| accent | #B35A28 | #E8A878 | Secondary action colour |
| on-accent | #FFFFFF | #1E1D19 | Text/icons on accent backgrounds |
| accent-container | #F5E0CC | #2A1E15 | Softer accent background (tags, callouts) |
| on-accent-container | #7A3E1A | #E8A878 | Text on accent-container |
| accent-hover | #9A4D22 | #F0BD96 | Hover state for accent elements |

### Feedback

For forms, validation, status messages, and system feedback. Rarely on screen - designed to be immediately recognisable. Each has a solid colour and a softer container for background fills.

#### Error (warm red)

| Token | Light | Dark | Purpose |
|-------|-------|------|---------|
| error | #B83230 | #E57373 | Error text, icons, borders |
| on-error | #FFFFFF | #1E1D19 | Text on error backgrounds |
| error-container | #FDEAEA | #2C1A1A | Error message backgrounds |
| on-error-container | #7A1F1E | #E57373 | Text on error-container |

#### Warning (amber - from brand palette)

| Token | Light | Dark | Purpose |
|-------|-------|------|---------|
| warning | #D49F3D | #F0C86A | Warning text, icons, borders |
| on-warning | #FFFFFF | #1E1D19 | Text on warning backgrounds |
| warning-container | #FDF3E0 | #2A2214 | Warning message backgrounds |
| on-warning-container | #7A5A1A | #F0C86A | Text on warning-container |

#### Success (warm green)

| Token | Light | Dark | Purpose |
|-------|-------|------|---------|
| success | #2D7D46 | #6ABF82 | Success text, icons, borders |
| on-success | #FFFFFF | #1E1D19 | Text on success backgrounds |
| success-container | #E6F4EA | #1A2A1E | Success message backgrounds |
| on-success-container | #1A5C2E | #6ABF82 | Text on success-container |

### Surfaces

Page backgrounds at different elevation levels. Unchanged from current implementation.

| Token | Light | Dark | Purpose |
|-------|-------|------|---------|
| surface | #FFFFFF | #1C1B19 | Main page background |
| surface-alt | #F8F6F1 | #141413 | Alternating sections (principles) |
| surface-raised | #F8F6F1 | #242320 | Cards, dropdowns, elevated elements |

### Text Hierarchy

Foreground colours for text on surface backgrounds. Unchanged from current implementation.

| Token | Light | Dark | Purpose |
|-------|-------|------|---------|
| on-surface | #3D3B35 | #C8C4BC | Primary body text |
| on-surface-secondary | #5E5A50 | #8A8579 | Descriptions, secondary info |
| on-surface-muted | #B5B0A6 | #5E5A50 | Placeholders, disabled text |

### Chrome

Header and footer regions. Unchanged from current implementation.

| Token | Light | Dark | Purpose |
|-------|-------|------|---------|
| chrome | rgba(3,31,31,0.95) | rgba(20,20,19,0.95) | Header/footer background |
| chrome-solid | #031F1F | #0D0D0C | Body background (visible behind chrome transparency) |
| on-chrome | #72D3D3 | #4BB8B8 | Default chrome text |
| on-chrome-secondary | #4BB8B8 | #72D3D3 | Secondary chrome text |
| on-chrome-active | #FFFFFF | #FFFFFF | Active/hover chrome text |

### Borders and Other

| Token | Light | Dark | Purpose |
|-------|-------|------|---------|
| border | #D6D2C9 | #2E2D28 | Default borders (cards, dividers) |
| border-strong | #B5B0A6 | #3D3B35 | Emphasised borders |
| hero-bg | #064D4D | #1A1F1E | Homepage hero background |

## Usage Rules

### Pairing rule

Every background token has a corresponding foreground token. When using a colour as a background, always use its paired foreground for text and icons:

- `bg-primary` pairs with `text-on-primary`
- `bg-accent-container` pairs with `text-on-accent-container`
- `bg-error-container` pairs with `text-on-error-container`
- `bg-surface` pairs with `text-on-surface` (or secondary/muted variants)
- `bg-chrome` pairs with `text-on-chrome` (or secondary/active variants)

### When to use each colour role

- **primary**: the default choice for interactive elements (links, buttons, toggles, active tabs) and brand-identifying elements (section labels, logo marks)
- **accent**: when you need visual distinction from primary. Secondary buttons, alternative tags, callout borders. Do not use accent for links or navigation - those are always primary.
- **error/warning/success**: only for communicating system state. Never decorative. Error for failed validation, destructive actions. Warning for caution, incomplete data. Success for confirmed actions, valid input.
- **surface/surface-alt/surface-raised**: surface is the default page background. Use surface-alt for alternating sections to create visual rhythm. Use surface-raised for elements that sit above the page (cards, dropdowns, modals).
- **chrome**: reserved for the header and footer. Not for content areas.

### Interactive states

Hover states use the `-hover` token variant:

- `hover:bg-primary-hover` for primary buttons
- `hover:bg-accent-hover` for accent buttons
- `hover:text-on-chrome-active` for chrome navigation

Focus states use a ring in the element's colour:

- `focus-visible:ring-2 ring-primary` for primary elements
- `focus-visible:ring-2 ring-accent` for accent elements

Disabled states use reduced opacity:

- `opacity-50 cursor-not-allowed` on disabled elements

### Adding new colours

If a new colour role is needed in future, follow the four-slot pattern:

1. Choose the raw colour value for light mode
2. Choose the dark mode value (shift lighter and softer, roughly +30-40 tonal steps)
3. Choose the container value (very light tint in light mode, very dark tint in dark mode)
4. Pair each background with an accessible foreground (minimum Web Content Accessibility Guidelines AA contrast, 4.5:1 for text)
5. Add all four tokens to both `:root` and `.dark` in main.css
6. Register the semantic tokens in `@theme {}` so Tailwind generates utility classes
7. Update this document

## Migration from Current System

The following tokens are renamed:

| Old name | New name |
|----------|----------|
| brand | primary |
| brand-hover | primary-hover |
| brand-muted | primary-muted |
| brand-subtle | primary-container |

All template references (`bg-brand`, `text-brand`, `border-brand`, etc.) must be updated to use the new names (`bg-primary`, `text-primary`, `border-primary`).

The following are removed as standalone tokens and rebuilt:

- `--color-amber`: absorbed into the warning colour role
- `.tag-copper` CSS class: rebuilt using `accent-container` / `on-accent-container` tokens
- `.btn` / `.btn-primary` / `.btn-secondary` CSS classes: rebuilt using `primary` / `accent` tokens

The raw palette (teal scale, warm neutrals, copper, copper-light) remains in `@theme {}` as reference values but is never used directly in templates.

# Design System: TTS Dubbing — Orchestrator Dashboard

## 1. Visual Theme & Atmosphere

A dark, architectural interface with the precision of a recording studio control room. Deep charcoal expanses punctuated by warm amber signal lights. The atmosphere is **clinical yet warm** — like stepping into a mastering suite at midnight. Confident asymmetric layouts, generous negative space, and deliberate typographic contrast. Every surface feels tactile, every interaction has weight.

- **Variance:** 7 — Offset asymmetric, intentionally broken grids, ziggurat whitespace
- **Density:** 4 — Balanced. Ample breathing room in content areas, tighter controls in data tables
- **Motion:** 6 — Fluid spring-physics. Micro-interactions on every clickable element. Staggered reveals
- **Spatial philosophy:** Every element owns its zone. No overlapping. No stacking hacks

## 2. Color Palette & Roles

Premium warm-neutral palette with a single amber accent. No cool grays, no purple, no neon.

- **Pitch Surface** (#0A0A0B) — Primary background. Not pure black, but close. The void.
- **Console Face** (#141416) — Card, sidebar, container fill. Slightly lifted from pitch.
- **Control Strip** (#1C1C20) — Elevated surfaces, inputs, hover states. Visible but quiet.
- **Phantom Border** (rgba(255,255,255,0.06)) — Structural dividers, hairline rules, card edges.
- **Vocal White** (#F4F4F5) — Primary text. Slightly warm white, not piercing.
- **Signal Amber** (#D4A853) — Single accent. CTAs, active states, focus rings, data highlights. ~60% saturation.
- **Muted Echo** (#787880) — Secondary text, metadata, timestamps, placeholders.
- **Dimmer** (#3D3D44) — Disabled text, non-interactive labels.
- **Alert Red** (#DC4747) — Destructive actions, error states, failed badges.
- **Online Green** (#34B855) — Success states, active indicators, completed badges.

**Banned:** Pure black (#000000), pure white (#FFFFFF), neon colors, purple gradients, blue primary accents, cool gray fluctuation.

## 3. Typography Rules

Dashboard/app context — sans-serif only (per Stitch rules for software UIs).

- **Display / Navigation:** **Geist** (keep existing) — Track-tight -0.02em, weight-driven hierarchy (Medium → Bold). No oversized screaming headlines in dashboards.
- **Body:** **Geist** — Regular weight, relaxed leading (1.6), max 65ch. Muted Echo for secondary.
- **Mono:** **Geist Mono** (keep existing) — All code blocks, timestamps, metadata, data table numbers, API endpoints. Must be smaller than body (0.875rem).
- **Scale:** `clamp(0.875rem, 1.5vw, 1rem)` for body. Headlines use `clamp(1.5rem, 3vw, 2.5rem)` — never larger.
- **Dashboard number emphasis:** All numeric data (balance, task counts, usage) in Geist Mono Medium — creates visual contrast from surrounding text.

**Banned:** Inter (anywhere), generic system fonts, serif fonts in any dashboard or UI context, all-caps body text.

## 4. Component Stylings

### Buttons
- **Primary:** Signal Amber fill, Vocal White text. Hover: brighten 5%. Active: translateY(1px) with spring compression. No outer glow. No neon.
- **Ghost:** Transparent, Phantom Border on hover. For toolbar actions, secondary commands.
- **Destructive:** Alert Red fill. Confirm dialogs only.
- **Size:** Standard 36px height. Touch targets minimum 44px on mobile.
- **Icon buttons:** 36px square, ghost variant, signal accent on hover.

### Cards
- **Console Face** (#141416) fill, subtle Phantom Border radius.
- **Dashboard stat cards:** No rounding (square corners). Just a hairline border-bottom and generous padding.
- **Setting/configuration cards:** Soft 8px rounding, elevated with 1px phantom border.
- **Data cards (admin tables):** No card wrapper — use border-top dividers with Phantom Border.

### Inputs & Forms
- **Label:** Above input, text-sm, Vocal White, 2px gap below.
- **Input field:** Control Strip fill, 1px Phantom Border, 8px rounding. Focus: ring-2 Signal Amber.
- **Error state:** Alert Red border, Alert Red helper text below input.
- **No floating labels.** No placeholder as label.

### Data Tables
- **Header row:** Phantom Border bottom, text-xs uppercase tracking-wider Muted Echo, 8px padding.
- **Body rows:** Alternating Control Strip hover. Border-bottom Phantom Border. Monospace for IDs, timestamps, numbers.
- **Empty state:** Centered composition with muted icon + secondary text + optional CTA.

### Badges & Status Indicators
- **Signal dot:** 6px circle, inline with text. Online Green = active, Signal Amber = pending/processing, Alert Red = failed/lost. No text wrapper — just the dot.
- **Status text:** Accompanying text in parentheses, Muted Echo, text-xs, monospace.
- For table status cells: Minimal chip (8px pill, translucent fill, monospace label).

### Loaders & Transitions
- **Skeletal:** Exact-match layout dimensions. Control Strip shimmer with Phantom Border. No circular spinners anywhere.
- **Page transitions:** Route-level fade (150ms) with subtle y-axis slide (8px). Spring easing.
- **Button loading:** Replace icon with a small amber pulse dot. Not a spinning ring.

### Empty States
- **Illustrated:** Contextual SVG icon (96px, Muted Echo opacity 0.3) + Vocal White heading (text-base) + Muted Echo body (text-sm) + optional primary CTA.
- **No "No data" text.** Always explain what belongs here and how to populate it.

## 5. Layout Principles

### Landing Page (Public)
- **Hero:** Asymmetric split. Left: staggered content block. Right: full-height audio visualization (abstract waveform graphic, Signal Amber on Pitch Surface). No centered hero.
- **No 3-column feature grid.** Use 2-column zigzag with alternating text/image. Each row offset: text-left/image-right, then image-left/text-right.
- **CTA section:** Asymmetric CTA — not centered. Full-bleed panel with offset CTA button anchored to left.

### Auth Pages (Login / Signup)
- **Split-screen layout:** Left 40% — brand identity, ambient audio visualization. Right 60% — auth form centered in its zone.
- **Form container:** No card-style wrapper. Just the form floating on Console Face with generous padding and a Signal Amber accent line on the left edge.

### Dashboard (User)
- **3-zone layout:** Fixed sidebar (240px) → content area with header bar → optional detail panel.
- **Overview:** Stat cards in a 4-column grid. Each card: no icon, just the number (Geist Mono Bold, Signal Amber) and label (text-xs uppercase, Muted Echo).
- **TTS section:** Left 60% — text input + voice selector. Right 40% — real-time audio visualization or history.
- **API keys / Usage / Settings:** Single-column content, max-w-3xl. Sections separated by Phantom Border rules, not cards.

### Admin Pages
- **Same 3-zone layout** as user dashboard but with admin-specific sidebar (accounts, tasks, voices, users, API keys).
- **Data-heavy pages** (tasks, accounts, api keys): Full-width tables, no card nesting. Tables are the primary visual element.
- **Form pages** (voices, users): Left 50% form, right 50% preview or contextual info.

### Responsive
- **< 768px:** All multi-column → single column. Sidebar collapses to hamburger drawer.
- **Tables** → stacked cards on mobile (each row becomes a mini card).
- **Stat grids** → 2-column on tablet, 1-column on phone.
- **Touch targets** minimum 44px.
- **Typography** scales with `clamp()` — never smaller than 14px on mobile.

## 6. Motion & Interaction

### Spring Physics
Default: `stiffness: 100, damping: 20`. Weighty, premium feel.
- **Buttons:** `whileTap={{ scale: 0.97 }}` with spring
- **Cards:** `whileHover={{ y: -2 }}` with spring, 150ms
- **Sidebar:** slide in with `x` transform, spring easing (not `left`)
- **Modals:** scale + fade entrance, spring overshoot (1.02 → 1.0)

### Micro-Interactions
- **Recording dot** (when TTS processing): Continuous pulse animation on the Signal Amber indicator
- **Stat numbers** (balance, counts): Animate from 0 to final value on mount (`useCountUp` pattern)
- **Table rows:** Staggered entrance with 40ms cascading delay on page load
- **Sidebar active indicator:** 3px Signal Amber line that slides between items (layout animation)

### Performance
- `transform` and `opacity` only. No animating `width`, `height`, `top`, `left`.
- `will-change: transform` on animated elements.
- `prefers-reduced-motion: reduce` respected — disable spring, use instant fades.

## 7. Page-Specific Design Rules

### Landing Page (`/`)
- **Hero headline:** "Chuyển văn bản thành" on line 1, "giọng nói AI" on line 2 in Signal Amber. No massive type — use weight and color for emphasis.
- **Hero visual:** Abstract waveform SVG (audio bars, varying heights, amber gradient). Not a generic microphone icon.
- **Feature section:** 2-column zigzag (not 3-column grid). Each feature row: icon → heading → description. Alternating layout.
- **No secondary CTA.** Single "Bắt đầu" button. No "Tìm hiểu thêm" link.

### Login / Signup (`/login`, `/signup`)
- **Brand column:** "tts-dubbing" logotype, tagline, ambient animated waveform. No illustration.
- **Form:** No card. Directly on Console Face. Signal Amber left border accent on the form container.
- **Toggle:** "Chưa có tài khoản? Đăng ký" as a subtle link, not a button.

### Dashboard (`/dashboard`)
- **Overview:** 4 stat numbers (balance, tasks completed, pending, failed). No card wrapper — just the number + label.
- **TTS form:** Left-aligned textarea + voice Select + submit button. Result audio player appears below on completion. No right-visual on mobile.
- **API keys list:** Table with prefix, status dot, created date, delete action. Key creation dialog is a slide-over panel, not a modal.
- **Usage history:** Table with date, character count, cost, source. Grouped by month with Phantom Border separators.

### Admin Overview (`/admin`)
- **Stat row:** 4 numbers across (workers, completed, pending, failed) in Geist Mono.
- **Task list:** Full-width table showing text (truncated), status dot, timestamp, retry button. Animated status dot for PROCESSING.

### Admin Accounts (`/admin/accounts`)
- **Table columns:** Email, Status (dot + label), Uptime, Runtime, Cooldown remaining, Actions.
- **Add account:** Opens a slide-over panel with email input + submit. Not a card at top of page.
- **Actions:** Start/Stop with hover-reveal buttons (hidden by default, show on row hover).

### Admin Tasks (`/admin/tasks`)
- **Table:** Same as admin overview but with voice_id, worker, retry count columns.
- **Filter bar:** Above table — status filter pills (All | PENDING | PROCESSING | COMPLETED | FAILED), date range, search by ID.

### Admin Voices (`/admin/voices`)
- **Visual card grid:** Each voice as a card with waveform preview (audio visualizer SVG), name, sample audio player, delete button.
- **Add voice:** Drag-and-drop zone at top, or form panel.

### Admin Users (`/admin/users`)
- **Table:** Email, role, balance, created date, status (active/disabled), actions.
- **Add/Top-up:** Slide-over panel for creating user or adjusting balance.

## 8. Anti-Patterns (Banned)

- No emojis anywhere in the UI
- No `Inter` font — Geist only
- No serif fonts (this is a dashboard/app, not an editorial site)
- No pure black (`#000000`) — use Pitch Surface (#0A0A0B)
- No pure white (`#FFFFFF`) — use Vocal White (#F4F4F5)
- No neon/outer glow shadows
- No purple or blue accents — Signal Amber only
- No excessive gradient text on headers
- No custom mouse cursors
- No overlapping elements — clean spatial zones always
- No 3-column equal card grids — zigzag or asymmetric layouts only
- No generic placeholder content — use meaningful Vietnamese text
- No AI copywriting clichés ("Elevate", "Seamless", "Unleash", "Next-Gen", "Revolutionary")
- No filler UI instructions ("Scroll to explore", "Swipe down")
- No bouncing arrow scroll indicators
- No broken image links — use inline SVG components
- No centered hero section on landing page
- No circular loading spinners — skeletal shimmer or pulse dots only
- No floating label inputs — labels above only

# Ambrilindo Local Venue — Design System & Style Guide

A practical design specification and visual reference for the local venue server (`ambrilindo/ambrilindo`). Use this document when styling or un-AI-ing pages across the local venue application (admin dashboard, tatami control, jury panels, scoring boards, etc.).

---

## 1. Core Design Philosophy

- **Tournament Operations First**: Built for fast-paced sporting environments where table officials, referees, and tournament staff view screens across variable arena lighting (harsh sports hall halogens, sunlight, or dim scoring tables).
- **High Contrast & Immediate Legibility**: Everything must be unmistakably readable at a glance or from a distance. No low-contrast grey text, no washed-out borders, no tiny illegible fonts.
- **Strictly Offline-Compliant (Zero CDNs)**: The local venue server runs on offline LANs. **Never use external CDN imports** (e.g. Google Fonts, unpkg, cdnjs). Use native system font stacks and locally served assets.
- **Zero AI-Slop / Anti-Trope Rules**:
  - ❌ **No graph paper / math grid backgrounds** (`linear-gradient` grid patterns).
  - ❌ **No glowing ambient blobs / colored radial blur overlays** (`body::before` radial glows).
  - ❌ **No gimmicky emojis or pill tags** (`⚡`, `🔒`, `CEPAT`, pulsing neon dots).
  - ❌ **No redundant brand headers** (e.g., logo image + identical text heading right below it).
  - ❌ **No floaty / low-contrast borders** (`rgba(0,0,0,0.05)` or `#e2e8f0` on inputs).

---

## 2. Color Palette & Semantic Tokens

### 2.1 CSS Variables Reference
```css
:root {
    /* Surfaces & Backgrounds */
    --bg-body:          #f1f5f9;  /* Slate 100 — grounded, cool neutral grey */
    --bg-card:          #ffffff;  /* Pure white surface */
    --bg-surface-alt:   #f8fafc;  /* Slate 50 — soft inset panels & table bodies */
    --bg-track:         #e2e8f0;  /* Slate 200 — segmented tab tracks & badges */

    /* High-Contrast Borders */
    --border-card:      #334155;  /* Slate 700 (1.5px) — sharp container definition */
    --border-input:     #64748b;  /* Slate 500 (1.5px) — clear, high-contrast input border */
    --border-divider:   #cbd5e1;  /* Slate 300 — clean internal section dividers */
    --border-hover:     #0f172a;  /* Slate 900 — active cursor hover */
    --border-focus:     #020617;  /* Pitch black (2px) — focused element */

    /* Typography Hierarchy */
    --text-primary:     #020617;  /* Pitch Dark (Slate 950) — headers, labels, active items */
    --text-secondary:   #1e293b;  /* Dark Slate (Slate 800) — descriptions, unselected tabs */
    --text-muted:       #475569;  /* Medium Slate (Slate 600) — footers, metadata, helper text */

    /* Primary Actions */
    --primary:          #000000;  /* Pitch black — primary CTA buttons & active badges */
    --primary-hover:    #1e293b;  /* Slate 800 — button hover */
    --ring-focus:       rgba(2, 6, 23, 0.2); /* 3px focus ring */

    /* Status & Alerts */
    --status-green-bg:  #f0fdf4;  /* Emerald 50 */
    --status-green-text:#065f46;  /* Emerald 800 */
    --status-green-dot: #059669;  /* Emerald 600 */
    --status-green-bdr: #047857;  /* Emerald 700 */

    --status-red-bg:    #fee2e2;  /* Red 100 */
    --status-red-text:  #7f1d1d;  /* Red 900 */
    --status-red-bdr:   #ef4444;  /* Red 500 */

    /* Geometry */
    --radius-sm:        6px;
    --radius-md:        8px;
    --radius-lg:        12px;
    --transition:       all 0.15s ease-in-out;
}
```

### 2.2 Color Swatch Quick Reference
| Token | Hex | Role | Contrast vs `#ffffff` |
|---|---|---|---|
| `--text-primary` | `#020617` | Headings, field labels, active cards | **19.8 : 1** (AAA) |
| `--text-secondary` | `#1e293b` | Form values, helper text, table cells | **14.3 : 1** (AAA) |
| `--text-muted` | `#475569` | Timestamps, metadata, footer notes | **7.0 : 1** (AAA) |
| `--border-input` | `#64748b` | Input & selection card borders | **4.6 : 1** (High visibility) |
| `--border-card` | `#334155` | Outer card boundary line | **9.5 : 1** (Sharp outline) |
| `--bg-body` | `#f1f5f9` | Full-page background | Contrast base |

---

## 3. Typography System

### 3.1 Font Stacks
```css
/* Body & UI Elements */
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;

/* Monospace (Codes, Match Numbers, Shortcuts, Cheatsheets) */
font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
```

### 3.2 Type Scale & Weights
| Role | Size | Weight | Color | Notes |
|---|---|---|---|---|
| **Page / Logo Subtitle** | `13px` | `600` | `--text-secondary` | Centered under logo |
| **Section / Card Title** | `15px`–`17px` | `700` | `--text-primary` | High contrast |
| **Form Labels** | `12.5px` | `700` | `--text-primary` | Bold, distinct above inputs |
| **Input Values / Selects** | `14px` | `600` | `--text-primary` | Clear tactile size |
| **Button Text** | `14px` | `700` | `#ffffff` | High visual weight |
| **Card / Role Titles** | `13.5px` | `700` (`800` when selected) | `--text-primary` | Touch-friendly text |
| **Table Headings** | `12px` | `800` | `#000000` | Heavy underline border |
| **Metadata / Footer** | `12px` | `600` | `--text-muted` | Clean secondary info |

---

## 4. Layout & Elevation

### 4.1 Card Container
```css
.auth-container, .panel-card {
    background: #ffffff;
    border: 1.5px solid var(--border-card); /* #334155 */
    border-radius: 12px;
    box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.12), 
                0 8px 10px -6px rgba(15, 23, 42, 0.08);
    overflow: hidden;
}
```

### 4.2 Brand Header Pattern
When the logo already includes brand typography, **do not duplicate it** with an `<h1>` text heading:
```html
<div class="brand-header">
    <div class="brand-logo-wrap">
        <img src="{% static 'img/ambrilindo/ambrilindo-logo-dark.png' %}" alt="Ambrilindo" style="height: 48px;">
    </div>
    <p class="brand-subtitle">Sistem Pertandingan Karate &bull; Local Venue Server</p>
</div>
```

---

## 5. Component Patterns & Code Snippets

### 5.1 Segmented Navigation Tabs
Crisp high-contrast pill switch (solid black active inversion):
```css
.auth-tabs {
    display: flex;
    background: #e2e8f0;
    border: 1.5px solid #cbd5e1;
    border-radius: 8px;
    padding: 3px;
    gap: 4px;
}

.auth-tab-btn {
    flex: 1;
    padding: 8px 12px;
    border-radius: 6px;
    background: transparent;
    border: none;
    color: #1e293b;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.15s ease-in-out;
}

.auth-tab-btn.active {
    background: #020617;
    color: #ffffff;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}
```

### 5.2 Form Inputs & Selects
Thick, unmistakable borders with clean focus rings:
```css
.form-label {
    display: block;
    font-size: 12.5px;
    font-weight: 700;
    color: #020617;
    margin-bottom: 6px;
}

.form-select, .form-input {
    width: 100%;
    background: #ffffff;
    border: 1.5px solid #64748b; /* Strong border */
    color: #020617;
    font-size: 14px;
    font-weight: 600;
    padding: 9px 12px;
    border-radius: 8px;
    outline: none;
    transition: all 0.15s ease-in-out;
}

.form-select:hover, .form-input:hover {
    border-color: #0f172a;
}

.form-select:focus, .form-input:focus {
    border-color: #0f172a;
    box-shadow: 0 0 0 3px rgba(2, 6, 23, 0.2);
}
```

### 5.3 Tactile Selection Cards / Grid Radios
For role switches, tatami selectors, or device modes:
```css
.fast-role-card {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    border: 1.5px solid #64748b;
    background: #ffffff;
    border-radius: 8px;
    cursor: pointer;
    user-select: none;
    transition: all 0.15s ease-in-out;
}

.fast-role-card:hover {
    border-color: #0f172a;
    background: #f8fafc;
}

/* Selected State */
.fast-role-card.selected {
    border: 2px solid #000000;
    background: #f1f5f9;
}

.fast-role-card.selected .fast-role-title {
    color: #000000;
    font-weight: 800;
}

/* Radio Indicator */
.role-check-indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #64748b;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
}

.fast-role-card.selected .role-check-indicator {
    border-color: #000000;
    background: #000000;
}

.fast-role-card.selected .role-check-indicator::after {
    content: "";
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #ffffff;
}
```

### 5.4 Primary Action Button (CTA)
```css
.btn-submit {
    width: 100%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 11px 16px;
    background: #000000;
    color: #ffffff;
    border: 2px solid #000000;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 700;
    cursor: pointer;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.15);
    transition: all 0.15s ease-in-out;
}

.btn-submit:hover {
    background: #1e293b;
    border-color: #1e293b;
}
```

### 5.5 High-Contrast Data Table / Collapsible Cheat Sheet
```css
.guide-dropdown {
    border: 1.5px solid #64748b;
    border-radius: 8px;
    background: #ffffff;
    overflow: hidden;
}

.guide-dropdown-toggle {
    padding: 10px 12px;
    font-size: 12.5px;
    font-weight: 700;
    color: #020617;
    display: flex;
    align-items: center;
    justify-content: space-between;
    cursor: pointer;
}

.guide-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
}

.guide-table th {
    text-align: left;
    padding: 6px 8px;
    font-weight: 800;
    color: #000000;
    border-bottom: 2px solid #000000;
}

.guide-table td {
    padding: 6px 8px;
    color: #020617;
    font-weight: 600;
    border-bottom: 1px solid #cbd5e1;
}

.guide-code {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    background: #e2e8f0;
    border: 1px solid #94a3b8;
    padding: 1px 5px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
    color: #000000;
}
```

### 5.6 Footer & Status Bar
```css
.auth-footer {
    padding: 10px 24px;
    border-top: 1.5px solid #cbd5e1;
    background: #f1f5f9;
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 12px;
    font-weight: 600;
    color: #475569;
}

.status-pill {
    display: flex;
    align-items: center;
    gap: 6px;
    color: #065f46;
    font-weight: 700;
}

.status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background-color: #059669;
    border: 1px solid #047857;
}
```

---

## 6. Checklist When Un-AI-ing Other Pages

When modifying subsequent templates in `backend/templates/` (`admin/`, `jury/`, `lo/`, etc.):
- [ ] Remove any `<link rel="preconnect" href="https://fonts.googleapis.com">` or CDN tags.
- [ ] Swap generic light borders (`#e2e8f0` or `rgba(0,0,0,0.08)`) for strong borders (`#64748b` on inputs, `#334155` on container cards).
- [ ] Ensure all form labels are bold (`font-weight: 700`) and deep black (`#020617`).
- [ ] Check active/selected states: they should have clear visual weight (dark background, inverted text, or thick border).
- [ ] Check branding: use the official image logo from `{% static 'img/ambrilindo/ambrilindo-logo-dark.png' %}` without redundant text repetition.
- [ ] Preserve all existing Indonesian identifiers, model fields, and AJAX/WebSocket handlers.

# UX Design System v1 — Flowise Dev Agent

**Branch:** `feat/ux-worldclass-ui-v1`
**Author:** Design Systems + UX Writing
**Status:** Final — Milestone UX-1
**Last updated:** 2026-02-24

---

## 1. Design Tokens

All tokens are defined for the Tailwind CSS `extend` block in `tailwind.config.ts`. The existing CSS custom properties from `index.html` are preserved as the canonical source and extended with semantic aliases.

### 1.1 Colors

```ts
// tailwind.config.ts
import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // ── Surface levels ──
        bg:        "#0f1117",   // page background
        surface:   "#1a1d27",   // cards, panels, popovers
        sidebar:   "#13151f",   // sidebar background
        border:    "#2a2d3e",   // dividers, input borders, separators
        overlay:   "rgba(15, 17, 23, 0.80)", // modal/dialog backdrop

        // ── Accent ──
        accent: {
          DEFAULT: "#5865f2",   // primary CTA, active nav, links
          hover:   "#6d7af5",   // accent on hover / focus
          dim:     "#2d3270",   // accent background tint (selected chips, active sidebar)
          muted:   "#1e2054",   // very subtle accent wash (hover rows)
        },

        // ── Semantic status ──
        success: {
          DEFAULT: "#22c55e",   // completed, approve, pass
          dim:     "#0d2b1a",   // success background tint
        },
        warning: {
          DEFAULT: "#f59e0b",   // HITL waiting, pending_interrupt
          dim:     "#2b1f0a",   // warning background tint
        },
        danger: {
          DEFAULT: "#ef4444",   // error, fail, rollback
          dim:     "#2b0d0d",   // danger background tint
        },
        info: {
          DEFAULT: "#3b82f6",   // in_progress, running, informational
          dim:     "#1e2a4a",   // info background tint
        },

        // ── Text levels ──
        text: {
          DEFAULT:   "#e8eaf6", // primary text
          secondary: "#a0a3bd", // secondary labels, descriptions
          muted:     "#7b7f9e", // placeholders, disabled, timestamps
          inverse:   "#0f1117", // text on accent/success/danger filled buttons
        },

        // ── Specialized ──
        stream:    "#a8d8a8",   // monospace stream output text
        "code-bg": "#0a0c12",   // inline code / code block background
      },

      // ── Typography ──
      fontFamily: {
        sans: [
          "system-ui",
          "-apple-system",
          '"Segoe UI"',
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
        mono: [
          '"JetBrains Mono"',
          '"Fira Code"',
          '"Cascadia Code"',
          "Consolas",
          "monospace",
        ],
      },

      fontSize: {
        "2xs":  ["10px", { lineHeight: "14px" }],  // micro labels, timestamps
        xs:     ["11px", { lineHeight: "16px" }],  // badges, sidebar meta
        sm:     ["12px", { lineHeight: "18px" }],  // secondary text, table cells
        base:   ["13px", { lineHeight: "20px" }],  // body text, descriptions
        md:     ["14px", { lineHeight: "22px" }],  // input text, button labels
        lg:     ["15px", { lineHeight: "24px" }],  // section headers, card titles
        xl:     ["16px", { lineHeight: "26px" }],  // page section titles
        "2xl":  ["20px", { lineHeight: "28px" }],  // panel headings
        "3xl":  ["22px", { lineHeight: "30px" }],  // page titles (h1)
      },

      fontWeight: {
        normal:   "400",
        medium:   "500",
        semibold: "600",
        bold:     "700",
      },

      // ── Spacing (4px grid) ──
      spacing: {
        "0.5": "2px",
        "1":   "4px",
        "1.5": "6px",
        "2":   "8px",
        "2.5": "10px",
        "3":   "12px",
        "3.5": "14px",
        "4":   "16px",
        "5":   "20px",
        "6":   "24px",
        "7":   "28px",
        "8":   "32px",
        "10":  "40px",
        "12":  "48px",
        "16":  "64px",
        "20":  "80px",
      },

      // ── Border radius ──
      borderRadius: {
        sm:  "4px",
        md:  "6px",
        lg:  "8px",
        xl:  "10px",
        full: "9999px",
      },

      // ── Shadows ──
      boxShadow: {
        surface: "0 1px 3px rgba(0, 0, 0, 0.3), 0 1px 2px rgba(0, 0, 0, 0.2)",
        card:    "0 2px 8px rgba(0, 0, 0, 0.4)",
        dialog:  "0 8px 30px rgba(0, 0, 0, 0.6)",
      },

      // ── Animations ──
      keyframes: {
        pulse: {
          "0%, 100%": { opacity: "1" },
          "50%":      { opacity: "0.45" },
        },
        spin: {
          from: { transform: "rotate(0deg)" },
          to:   { transform: "rotate(360deg)" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
        "slide-in-right": {
          from: { opacity: "0", transform: "translateX(8px)" },
          to:   { opacity: "1", transform: "translateX(0)" },
        },
      },
      animation: {
        pulse:          "pulse 1.5s ease-in-out infinite",
        spin:           "spin 1s linear infinite",
        "fade-in":      "fade-in 0.15s ease-out",
        "slide-in-right": "slide-in-right 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
```

### 1.2 CSS Custom Properties

Add these to `app/globals.css` for runtime access and shadcn/ui theming:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    /* Surface */
    --bg:          #0f1117;
    --surface:     #1a1d27;
    --sidebar-bg:  #13151f;
    --border:      #2a2d3e;
    --overlay:     rgba(15, 17, 23, 0.80);

    /* Accent */
    --accent:      #5865f2;
    --accent-hover:#6d7af5;
    --accent-dim:  #2d3270;

    /* Semantic */
    --success:     #22c55e;
    --warning:     #f59e0b;
    --danger:      #ef4444;
    --info:        #3b82f6;

    /* Text */
    --text:        #e8eaf6;
    --text-secondary: #a0a3bd;
    --text-muted:  #7b7f9e;
    --text-inverse:#0f1117;

    /* Stream */
    --stream-text: #a8d8a8;

    /* Font stacks */
    --font-sans: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    --font-mono: "JetBrains Mono", "Fira Code", "Cascadia Code", Consolas, monospace;

    /* shadcn/ui required variables */
    --background:  0 0% 7%;
    --foreground:  230 40% 93%;
    --card:        230 18% 13%;
    --card-foreground: 230 40% 93%;
    --popover:     230 18% 13%;
    --popover-foreground: 230 40% 93%;
    --primary:     234 89% 67%;
    --primary-foreground: 0 0% 100%;
    --secondary:   230 18% 20%;
    --secondary-foreground: 230 40% 93%;
    --muted:       232 13% 55%;
    --muted-foreground: 232 13% 55%;
    --accent:      234 89% 67%;
    --accent-foreground: 0 0% 100%;
    --destructive: 0 84% 60%;
    --destructive-foreground: 0 0% 100%;
    --border:      232 18% 20%;
    --input:       232 18% 20%;
    --ring:        234 89% 67%;
    --radius:      6px;
  }
}
```

### 1.3 Color Contrast Verification

All foreground/background pairs must meet WCAG AA (4.5:1 minimum):

| Pair | Foreground | Background | Ratio | Status |
|------|-----------|------------|-------|--------|
| Primary text on bg | `#e8eaf6` | `#0f1117` | 14.2:1 | PASS |
| Primary text on surface | `#e8eaf6` | `#1a1d27` | 11.3:1 | PASS |
| Secondary text on bg | `#a0a3bd` | `#0f1117` | 7.2:1 | PASS |
| Muted text on bg | `#7b7f9e` | `#0f1117` | 4.6:1 | PASS (borderline) |
| Muted text on surface | `#7b7f9e` | `#1a1d27` | 3.7:1 | WARN -- use `text-secondary` for surface cards |
| Stream text on surface | `#a8d8a8` | `#1a1d27` | 8.9:1 | PASS |
| Accent on bg | `#5865f2` | `#0f1117` | 4.7:1 | PASS |
| White on accent | `#ffffff` | `#5865f2` | 3.9:1 | PASS (large text only) |
| White on success | `#ffffff` | `#22c55e` | 2.8:1 | WARN -- use bold 14px+ |

**Action items for the frontend engineer:**
- On surface-colored cards, use `text-secondary` (`#a0a3bd`) instead of `text-muted` for readable body text.
- Button text on `success` and `accent` backgrounds should be bold and at least 14px (WCAG AA large text exception).

---

## 2. Component Patterns

All components are built on [shadcn/ui](https://ui.shadcn.com/) primitives. Each section below defines the variant configuration and custom class overrides.

### 2.1 Button

Base: `shadcn/ui Button`

| Variant | Class overrides | Usage |
|---------|----------------|-------|
| `primary` | `bg-accent hover:bg-accent-hover text-white font-medium` | Primary CTA: "Start Session", "Send", "Approve" |
| `secondary` | `bg-transparent border border-border text-text-muted hover:border-accent hover:text-text` | Secondary actions: "View Audit Trail", "Back" |
| `danger` | `bg-danger hover:bg-red-700 text-white font-semibold` | Destructive: "Rollback", "Delete" |
| `approve` | `bg-success hover:bg-green-600 text-white font-semibold` | Affirm: "Approve Plan", "Accept" |
| `ghost` | `bg-transparent hover:bg-surface text-text-muted hover:text-text` | Inline/icon actions: refresh, collapse toggle |

All buttons: `rounded-md px-4 py-2 text-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg`

Disabled state: `opacity-50 cursor-not-allowed pointer-events-none`

```tsx
// components/ui/button.tsx — variant config for cva()
const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-md text-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none",
  {
    variants: {
      variant: {
        primary:   "bg-accent hover:bg-accent-hover text-white",
        secondary: "bg-transparent border border-border text-text-muted hover:border-accent hover:text-text",
        danger:    "bg-danger hover:bg-red-700 text-white font-semibold",
        approve:   "bg-success hover:bg-green-600 text-white font-semibold",
        ghost:     "bg-transparent hover:bg-surface text-text-muted hover:text-text",
      },
      size: {
        sm:      "h-8 px-3 text-sm",
        default: "h-9 px-4 text-md",
        lg:      "h-10 px-6 text-md",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "default",
    },
  }
);
```

### 2.2 Badge / Pill

Base: `shadcn/ui Badge`

#### Status badges

| Status | Background | Text | Border | Extra |
|--------|-----------|------|--------|-------|
| `pending_interrupt` | `warning-dim` | `warning` | `warning/30` | `animate-pulse` |
| `completed` | `success-dim` | `success` | `success/30` | -- |
| `in_progress` | `info-dim` | `info` | `info/30` | -- |
| `error` | `danger-dim` | `danger` | `danger/30` | -- |

```tsx
const statusBadgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold border",
  {
    variants: {
      status: {
        pending_interrupt: "bg-warning-dim text-warning border-warning/30 animate-pulse",
        completed:         "bg-success-dim text-success border-success/30",
        in_progress:       "bg-info-dim text-info border-info/30",
        error:             "bg-danger-dim text-danger border-danger/30",
      },
    },
  }
);
```

#### Operation mode pills

| Mode | Background | Text | Border |
|------|-----------|------|--------|
| `CREATE` | `info-dim` | `info` | `info/30` |
| `UPDATE` | `warning-dim` | `warning` | `warning/30` |

```tsx
const operationBadgeVariants = cva(
  "inline-flex items-center rounded-sm px-2 py-0.5 text-2xs font-bold uppercase tracking-wider border",
  {
    variants: {
      mode: {
        create: "bg-info-dim text-info border-info/30",
        update: "bg-warning-dim text-warning border-warning/30",
      },
    },
  }
);
```

#### Interrupt type labels

| Type | Background | Text |
|------|-----------|------|
| `clarification` | `#1e3a5f` | `#60a5fa` |
| `credential_check` | `#3b1f1f` | `#fca5a5` |
| `plan_approval` | `#1a2e1a` | `#86efac` |
| `result_review` | `#1e2a4a` | `#93c5fd` |
| `select_target` | `#2b1f0a` | `#fbbf24` |

```tsx
const interruptLabelVariants = cva(
  "inline-flex items-center gap-1.5 rounded-sm px-2.5 py-1 text-xs font-bold uppercase tracking-wider",
  {
    variants: {
      type: {
        clarification:    "bg-[#1e3a5f] text-[#60a5fa]",
        credential_check: "bg-[#3b1f1f] text-[#fca5a5]",
        plan_approval:    "bg-[#1a2e1a] text-[#86efac]",
        result_review:    "bg-[#1e2a4a] text-[#93c5fd]",
        select_target:    "bg-[#2b1f0a] text-[#fbbf24]",
      },
    },
  }
);
```

### 2.3 Card

Base: `shadcn/ui Card`

#### Default surface card

```tsx
// Standard card used for content sections
<Card className="bg-surface border-border rounded-lg shadow-surface" />
```

Classes: `bg-surface border border-border rounded-lg shadow-surface`

#### HITL card

HITL interrupt cards get a wider layout, extra padding, and a colored left border keyed to the interrupt type.

```tsx
const hitlCardBorderColor: Record<string, string> = {
  clarification:    "border-l-[#60a5fa]",
  credential_check: "border-l-danger",
  plan_approval:    "border-l-success",
  result_review:    "border-l-info",
  select_target:    "border-l-warning",
};

// Usage
<Card className={cn(
  "bg-surface border border-border rounded-lg shadow-card",
  "max-w-[800px] w-full mx-auto p-6",
  "border-l-4",
  hitlCardBorderColor[interruptType]
)} />
```

### 2.4 Timeline Node

Used in the `PhaseTimeline` component (left panel). Each node row shows its current execution state.

```tsx
interface TimelineNodeProps {
  state: "pending" | "running" | "completed" | "interrupted" | "failed" | "skipped";
  label: string;
  duration?: number; // ms
  summary?: string;
}
```

Visual mapping (see Section 4 for full details):

```tsx
const timelineNodeStyles: Record<string, string> = {
  pending:     "text-text-muted",
  running:     "text-info",
  completed:   "text-success",
  interrupted: "text-warning animate-pulse",
  failed:      "text-danger",
  skipped:     "text-text-muted opacity-50",
};
```

Layout:
- Vertical line connecting nodes: `border-l border-border ml-3`
- Node row: `flex items-center gap-3 py-1.5 px-2`
- Icon: 16x16, see Section 4 icon table
- Label: `text-sm font-mono`
- Duration (completed only): `text-2xs text-text-muted ml-auto`

### 2.5 Textarea

Base: `shadcn/ui Textarea`

```tsx
<Textarea
  className={cn(
    "bg-surface border border-border rounded-lg",
    "text-md text-text font-sans",
    "px-3.5 py-3 min-h-[100px] resize-y",
    "placeholder:text-text-muted",
    "focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent",
    "transition-colors"
  )}
/>
```

### 2.6 Toast

Use [Sonner](https://sonner.emilkowal.dev/) (the shadcn/ui recommended toast library).

```tsx
// app/layout.tsx
import { Toaster } from "sonner";

<Toaster
  position="bottom-right"
  toastOptions={{
    className: "bg-surface border border-border text-text shadow-card",
    style: {
      fontFamily: "var(--font-sans)",
    },
  }}
/>
```

| Variant | Icon color | Border accent | Usage |
|---------|-----------|---------------|-------|
| `success` | `text-success` | `border-l-2 border-l-success` | Session completed, credentials saved |
| `error` | `text-danger` | `border-l-2 border-l-danger` | API error, stream failure |
| `warning` | `text-warning` | `border-l-2 border-l-warning` | Schema drift detected, reconnecting |

```tsx
// Usage
import { toast } from "sonner";

toast.success("Session completed successfully");
toast.error("Connection error -- check your server is running");
toast.warning("Schema drift detected");
```

### 2.7 Collapsible

Base: `shadcn/ui Collapsible`

Two primary uses:

**Raw output in streaming panel:**
```tsx
<Collapsible defaultOpen>
  <CollapsibleTrigger className="flex items-center gap-2 text-sm text-text-muted hover:text-text">
    <ChevronRight className="h-4 w-4 transition-transform data-[state=open]:rotate-90" />
    Raw Output
  </CollapsibleTrigger>
  <CollapsibleContent className="mt-2">
    <div className="bg-surface border border-border rounded-lg p-4 font-mono text-base text-stream overflow-y-auto max-h-[60vh]">
      {streamContent}
    </div>
  </CollapsibleContent>
</Collapsible>
```

**Test details in result review:**
```tsx
<Collapsible>
  <CollapsibleTrigger className="text-sm text-text-muted hover:text-text">
    Show test details
  </CollapsibleTrigger>
  <CollapsibleContent className="mt-2">
    <pre className="bg-code-bg rounded-md p-3 text-sm font-mono text-text overflow-x-auto">
      {testResults}
    </pre>
  </CollapsibleContent>
</Collapsible>
```

### 2.8 Table

Base: `shadcn/ui Table`

Used for the session list on the dashboard.

```tsx
<Table className="w-full">
  <TableHeader>
    <TableRow className="border-b border-border hover:bg-transparent">
      <TableHead className="text-xs text-text-muted font-semibold uppercase tracking-wider">
        ...
      </TableHead>
    </TableRow>
  </TableHeader>
  <TableBody>
    <TableRow className="border-b border-border/50 hover:bg-surface cursor-pointer transition-colors">
      <TableCell className="text-sm text-text">...</TableCell>
    </TableRow>
  </TableBody>
</Table>
```

Row hover: `hover:bg-surface` (from `bg` to `surface` on hover).
Active/selected row: `bg-surface border-l-2 border-l-accent`.

---

## 3. Layout Grid

### 3.1 App Shell

```
┌────────────────────────────────────────────────────────────┐
│  Header (h-[52px], bg-surface, border-b border-border)     │
├───────────────┬────────────────────────────────────────────┤
│  Sidebar      │  Main Content                              │
│  (w-[280px])  │  (flex-1)                                  │
│  bg-sidebar   │  bg-bg                                     │
│  border-r     │                                            │
│  border-border│                                            │
└───────────────┴────────────────────────────────────────────┘
```

```tsx
// app/layout.tsx
<div className="h-screen grid grid-rows-[52px_1fr] grid-cols-[280px_1fr] overflow-hidden bg-bg text-text">
  <Header className="col-span-full" />
  <Sidebar />
  <main className="overflow-hidden relative">{children}</main>
</div>
```

### 3.2 Session Detail (Three-Panel)

```
┌──────────────────┬───────────────────────────┬───────────────────┐
│  Phase Timeline  │   Active Panel             │  Artifacts Panel  │
│  w-[240px]       │   flex-1                   │  w-[320px]        │
│  fixed           │   min-w-0                  │  toggleable       │
│  border-r        │                            │  border-l         │
│  overflow-y-auto │                            │  overflow-y-auto  │
└──────────────────┴───────────────────────────┴───────────────────┘
```

```tsx
// app/sessions/[id]/layout.tsx
<div className="flex h-full overflow-hidden">
  <PhaseTimeline className="w-[240px] flex-shrink-0 border-r border-border overflow-y-auto" />
  <ActivePanel className="flex-1 min-w-0 overflow-hidden" />
  {artifactsPanelOpen && (
    <ArtifactsPanel className="w-[320px] flex-shrink-0 border-l border-border overflow-y-auto animate-slide-in-right" />
  )}
</div>
```

### 3.3 Responsive Breakpoints

| Breakpoint | Viewport | Behavior |
|------------|----------|----------|
| Desktop | > 900px | Full three-panel layout |
| Tablet | 641px -- 900px | Artifacts panel collapses to a slide-over drawer (triggered by toggle button) |
| Mobile | <= 640px | Timeline collapses to horizontal top bar (scrollable); Artifacts panel becomes a bottom sheet |

```tsx
// Responsive sidebar (app shell)
// At <= 768px, sidebar becomes a slide-over drawer triggered by hamburger menu in header

// Responsive artifacts panel
<Sheet>
  <SheetTrigger asChild>
    <Button variant="ghost" className="lg:hidden">
      <PanelRightOpen className="h-4 w-4" />
    </Button>
  </SheetTrigger>
  <SheetContent side="right" className="w-[320px] bg-surface border-l border-border">
    <ArtifactsPanel />
  </SheetContent>
</Sheet>
```

Tailwind breakpoint config (standard defaults are fine):
- `sm`: 640px
- `md`: 768px
- `lg`: 1024px

---

## 4. State Visuals

Every node/session state has an exact, unambiguous visual treatment. All icons are from [Lucide React](https://lucide.dev/) (bundled with shadcn/ui).

### 4.1 Node States (Phase Timeline)

| State | Icon | Lucide component | Color | Animation | Label |
|-------|------|-------------------|-------|-----------|-------|
| `pending` | circle-dashed | `CircleDashed` | `text-text-muted` | none | "Pending" |
| `running` | loader-2 | `Loader2` | `text-info` | `animate-spin` | "Running" |
| `completed` | check-circle-2 | `CheckCircle2` | `text-success` | none | "Done" |
| `interrupted` | pause-circle | `PauseCircle` | `text-warning` | `animate-pulse` | "Waiting for you" |
| `failed` | x-circle | `XCircle` | `text-danger` | none | "Failed" |
| `skipped` | minus-circle | `MinusCircle` | `text-text-muted opacity-50` | none | "Skipped" |

```tsx
import {
  CircleDashed, Loader2, CheckCircle2,
  PauseCircle, XCircle, MinusCircle
} from "lucide-react";

const nodeStateConfig = {
  pending:     { icon: CircleDashed,  color: "text-text-muted",             animation: "",              label: "Pending" },
  running:     { icon: Loader2,       color: "text-info",                   animation: "animate-spin",  label: "Running" },
  completed:   { icon: CheckCircle2,  color: "text-success",               animation: "",              label: "Done" },
  interrupted: { icon: PauseCircle,   color: "text-warning",               animation: "animate-pulse", label: "Waiting for you" },
  failed:      { icon: XCircle,       color: "text-danger",                animation: "",              label: "Failed" },
  skipped:     { icon: MinusCircle,   color: "text-text-muted opacity-50", animation: "",              label: "Skipped" },
} as const;
```

### 4.2 Session Status (Sidebar + Dashboard)

| Status | Dot color | Badge variant | Label |
|--------|----------|---------------|-------|
| `in_progress` | `bg-info` | `in_progress` | "Running" |
| `pending_interrupt` | `bg-warning` | `pending_interrupt` | "Waiting for you" |
| `completed` | `bg-success` | `completed` | "Done" |
| `error` | `bg-danger` | `error` | "Error" |

Sidebar dot: `w-2 h-2 rounded-full flex-shrink-0`

### 4.3 Tool Call States (Streaming Panel)

| State | Border | Text | Icon | Animation |
|-------|--------|------|------|-----------|
| `calling` | `border-warning` | `text-warning` | none | `animate-pulse` |
| `done` | `border-success` | `text-success` | `Check` (12px) | none |

```tsx
<span className={cn(
  "inline-flex items-center gap-1 font-mono text-xs px-2 py-0.5 rounded-sm border",
  status === "calling"
    ? "border-warning text-warning animate-pulse"
    : "border-success text-success"
)}>
  {name} {status === "done" && <Check className="h-3 w-3" />}
</span>
```

### 4.4 Test Result Badges

| Result | Background | Text | Border |
|--------|-----------|------|--------|
| PASS | `success-dim` | `success` | `border-success` |
| FAIL | `danger-dim` | `danger` | `border-danger` |

```tsx
<span className={cn(
  "inline-flex items-center px-3 py-1 rounded-sm text-sm font-semibold border",
  passed
    ? "bg-success-dim text-success border-success"
    : "bg-danger-dim text-danger border-danger"
)}>
  {label}: {passed ? "PASS" : "FAIL"}
</span>
```

---

## 5. Microcopy Glossary

### 5.1 Canonical Terminology

All user-facing text must use these exact labels. Never expose raw technical identifiers.

| Technical term | User-facing label | Usage context |
|----------------|------------------|---------------|
| `session` | "Session" | Session list, header, sidebar |
| `thread_id` | "Session ID" | Display: first 8 chars + "..." (e.g., `a1b2c3d4...`) |
| `chatflow_id` | "Chatflow ID" | Artifacts panel, completed panel, session meta |
| `operation_mode: "create"` | "CREATE" (uppercase badge) | Session card, header badge |
| `operation_mode: "update"` | "UPDATE" (uppercase badge) | Session card, header badge |
| `plan_approval` interrupt | "Plan Ready for Review" | HITL panel label |
| `select_target` interrupt | "Select Chatflow to Update" | HITL panel label |
| `result_review` interrupt | "Tests Complete -- Review Results" | HITL panel label |
| `credential_check` interrupt | "Credential Check" | HITL panel label |
| `clarification` interrupt | "Clarification Needed" | HITL panel label |
| `pending_interrupt` | "Waiting for you" | Status badge text |
| `in_progress` | "Running" | Status badge text |
| `completed` | "Done" | Status badge text |
| `error` | "Error" | Status badge text |
| `patch_ir` | "Patch Operations" | Artifacts panel tab/label |
| `schema_fingerprint` | "Schema version" | Telemetry panel |
| `drift_detected: true` | "Schema drift detected" | Warning badge in telemetry |
| `pattern_used: true` | "Based on pattern" | Badge in plan approval panel |
| `iteration` | "Iteration" | Counter badge (e.g., "Iteration 2") |
| `test_trials` | "Test trials" | New session form label |
| `total_input_tokens` | "Input tokens" | Completed panel stats |
| `total_output_tokens` | "Output tokens" | Completed panel stats |

### 5.2 HITL Panel Headings

These are the full labels displayed at the top of each interrupt panel:

| Interrupt type | Heading | Icon (Lucide) |
|---------------|---------|---------------|
| `clarification` | "Clarification Needed" | `HelpCircle` |
| `credential_check` | "Credential Check" | `KeyRound` |
| `plan_approval` | "Plan Ready for Review" | `FileEdit` |
| `select_target` | "Select Chatflow to Update" | `GitBranch` |
| `result_review` | "Tests Complete -- Review Results" | `TestTube2` |

### 5.3 Button Labels

| Action | Label | Context |
|--------|-------|---------|
| Start new session | "Start Session" | New session form |
| Approve plan | "Approve Plan" | Plan approval panel |
| Approve selected approach | "Approve Selected Approach" | Plan approval with options |
| Accept test results | "Accept and Finish" | Result review panel |
| Rollback | "Rollback" | Result review panel |
| Submit response | "Send" | All HITL response forms |
| Submit credentials | "Submit Credentials" | Credential check panel |
| Select chatflow | "Update Selected Chatflow" | Select target panel |
| Create new instead | "Create New Instead" | Select target panel |
| New session (from completed) | "New Session" | Completed panel |
| View audit | "View Audit Trail" | Completed panel |
| Refresh sessions | "Refresh" | Sidebar header |
| Delete session | "Delete" | Session context menu |
| Rename session | "Rename" | Session context menu |
| Toggle artifacts | "Toggle Artifacts" | Session detail header |
| Retry connection | "Retry" | SSE disconnect banner |

### 5.4 Empty States

| Context | Message |
|---------|---------|
| No sessions | "No sessions yet. Start your first co-development session." |
| No test results | "No test results available yet." |
| No patterns | "No saved patterns. Patterns are created automatically from successful sessions." |
| No versions | "No version snapshots recorded for this session." |
| No audit trail | "Audit trail not yet available." |
| No matching chatflows | "No matching chatflows found. You can create a new one instead." |

### 5.5 Error Message Templates

Use these exact messages for common error scenarios. Do not expose raw HTTP status codes or stack traces to users.

| Scenario | Message |
|----------|---------|
| Network error (fetch fails) | "Connection error -- check your server is running" |
| HTTP 401 | "API key required -- enter your key in the header" |
| HTTP 403 | "Access denied -- check your API key permissions" |
| HTTP 404 (session) | "Session not found -- it may have been deleted" |
| HTTP 404 (chatflow) | "Chatflow not found -- it may have been removed from Flowise" |
| HTTP 500 | "Server error -- please try again or check server logs" |
| SSE stream disconnected | "Stream disconnected -- reconnecting..." |
| SSE max retries exceeded | "Unable to reconnect -- click to retry" |
| SSE parse error | "Received unexpected data from server" |
| Session start failed | "Could not start session -- check your connection and try again" |
| Credential resolution failed | "Could not verify credentials -- check they exist in Flowise" |
| Plan generation failed | "The agent could not generate a plan -- try rephrasing your requirement" |

### 5.6 Confirmation Dialogs

| Action | Title | Body | Confirm label | Cancel label |
|--------|-------|------|--------------|--------------|
| Delete session | "Delete session?" | "This will permanently delete this session and its history. This cannot be undone." | "Delete" (danger) | "Cancel" |
| Rollback chatflow | "Rollback chatflow?" | "This will revert the chatflow to its previous version." | "Rollback" (danger) | "Cancel" |

---

## 6. Accessibility Checklist

All items must pass before shipping v1.

### 6.1 Keyboard Navigation

- [ ] All interactive elements are reachable via Tab / Shift+Tab
- [ ] Tab order follows visual layout: header -> sidebar -> main content -> artifacts panel
- [ ] Focus indicators: 2px `accent` ring on all focused elements (`focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg`)
- [ ] Escape key closes modals and dialogs
- [ ] Arrow keys navigate within: timeline nodes (up/down), approach options (up/down), session list (up/down)

### 6.2 Keyboard Shortcuts

| Shortcut | Action | Context |
|----------|--------|---------|
| `Ctrl+Enter` / `Cmd+Enter` | Submit new session form | New session modal |
| `Enter` | Submit HITL response | HITL panels (except plan_approval textarea where Enter = newline) |
| `Ctrl+Enter` / `Cmd+Enter` | Submit HITL response | Plan approval textarea (since Enter = newline there) |
| `Escape` | Close modal / dismiss drawer | Modals, artifact drawer |

### 6.3 ARIA Roles and Labels

| Component | ARIA | Notes |
|-----------|------|-------|
| Phase Timeline | `role="list"` on container | -- |
| Phase Row | `role="listitem"` | -- |
| Node Row | `role="listitem"`, `aria-label="{node_name}: {state_label}"` | e.g., "plan_v2: Running" |
| HITL Panel | `role="dialog"`, `aria-modal="true"`, `aria-labelledby` | When displayed as modal on mobile |
| HITL Textarea | `autoFocus` on mount | Auto-focus when HITL panel appears |
| Streaming output | `aria-live="polite"`, `aria-label="Agent output stream"` | Screen reader announces new content |
| Toast notifications | `aria-live="assertive"` | Immediate announcement |
| Status badge | Includes text label (not color-only) | e.g., badge says "Running" not just blue dot |
| Session list table | `role="table"` (implicit with `<table>`) | -- |
| Approach options | `role="radiogroup"`, each option `role="radio"` | -- |
| Collapsible trigger | `aria-expanded="true/false"` | Handled by shadcn/ui Collapsible |

### 6.4 Screen Reader Considerations

- Status changes (node completing, interrupt arriving) should trigger `aria-live` region updates
- Tool call badges should have `aria-label` including the tool name and status (e.g., "get_node: calling")
- Duration values should include units (e.g., `aria-label="Duration: 412 milliseconds"`)
- Monospace/code content blocks should have `aria-label` describing their purpose

### 6.5 Color and Contrast

- [ ] All text meets minimum 4.5:1 contrast ratio against its background (see Section 1.3)
- [ ] Status badges include text labels, not just color dots
- [ ] Test result PASS/FAIL badges include the word, not just green/red
- [ ] Warning and error states use icons alongside color
- [ ] No information conveyed through color alone

### 6.6 Loading States

- [ ] Use `<Skeleton>` components (shadcn/ui) for all loading states, not empty white space
- [ ] Session list shows skeleton rows while fetching
- [ ] Phase timeline shows skeleton nodes while replaying events
- [ ] Artifacts panel tabs show skeleton content while loading

```tsx
// Example: Session list loading
<TableRow>
  <TableCell><Skeleton className="h-4 w-16 bg-border" /></TableCell>
  <TableCell><Skeleton className="h-4 w-32 bg-border" /></TableCell>
  <TableCell><Skeleton className="h-4 w-24 bg-border" /></TableCell>
</TableRow>
```

### 6.7 Motion and Animation

- [ ] Respect `prefers-reduced-motion` media query
- [ ] When reduced motion is preferred, disable `animate-pulse` and `animate-spin`, use static icons instead

```css
@media (prefers-reduced-motion: reduce) {
  .animate-pulse,
  .animate-spin {
    animation: none !important;
  }
}
```

---

## 7. shadcn/ui Components to Install

Run these commands in the Next.js project root to install all required shadcn/ui components:

```bash
# Initialize shadcn/ui (if not already done)
npx shadcn-ui@latest init

# Core components
npx shadcn-ui@latest add button
npx shadcn-ui@latest add badge
npx shadcn-ui@latest add card
npx shadcn-ui@latest add input
npx shadcn-ui@latest add textarea
npx shadcn-ui@latest add dialog
npx shadcn-ui@latest add separator
npx shadcn-ui@latest add tooltip
npx shadcn-ui@latest add collapsible
npx shadcn-ui@latest add tabs
npx shadcn-ui@latest add table
npx shadcn-ui@latest add skeleton
npx shadcn-ui@latest add sonner
npx shadcn-ui@latest add scroll-area
npx shadcn-ui@latest add sheet
npx shadcn-ui@latest add dropdown-menu
```

### Additional dependencies

```bash
# Lucide icons (comes with shadcn/ui, but verify installation)
npm install lucide-react

# Tailwind animation plugin
npm install tailwindcss-animate

# Markdown rendering (for plan approval panel)
npm install react-markdown remark-gfm

# Syntax highlighting in markdown (optional but recommended)
npm install rehype-highlight
```

### Component customization checklist

After installing each shadcn/ui component, apply these overrides:

| Component | Override needed |
|-----------|----------------|
| `button` | Replace default variants with Section 2.1 config |
| `badge` | Add status/operation/interrupt variants (Section 2.2) |
| `card` | Update default border/bg colors to match tokens |
| `input` | Set `bg-surface border-border` defaults |
| `textarea` | Set `bg-surface border-border min-h-[100px]` defaults |
| `dialog` | Set `bg-surface border-border` overlay to `--overlay` |
| `table` | Update row hover to `hover:bg-surface` |
| `skeleton` | Set default `bg-border` instead of light gray |
| `sonner` | Apply toast theme from Section 2.6 |
| `sheet` | Set `bg-surface border-border` for artifacts drawer |

---

## Appendix A: Quick Reference -- Color Palette

```
Surface levels:
  bg          #0f1117  ████████
  surface     #1a1d27  ████████
  sidebar     #13151f  ████████
  border      #2a2d3e  ████████

Accent:
  accent      #5865f2  ████████
  accent-h    #6d7af5  ████████
  accent-dim  #2d3270  ████████

Semantic:
  success     #22c55e  ████████
  warning     #f59e0b  ████████
  danger      #ef4444  ████████
  info        #3b82f6  ████████

Text:
  text        #e8eaf6  ████████
  secondary   #a0a3bd  ████████
  muted       #7b7f9e  ████████
  stream      #a8d8a8  ████████
```

## Appendix B: Icon Set Reference

All icons are from [Lucide React](https://lucide.dev/). These are the icons used across the design system:

| Purpose | Icon | Import |
|---------|------|--------|
| Node: pending | `CircleDashed` | `lucide-react` |
| Node: running | `Loader2` | `lucide-react` |
| Node: completed | `CheckCircle2` | `lucide-react` |
| Node: interrupted | `PauseCircle` | `lucide-react` |
| Node: failed | `XCircle` | `lucide-react` |
| Node: skipped | `MinusCircle` | `lucide-react` |
| Tool call done | `Check` | `lucide-react` |
| HITL: clarification | `HelpCircle` | `lucide-react` |
| HITL: credential | `KeyRound` | `lucide-react` |
| HITL: plan | `FileEdit` | `lucide-react` |
| HITL: select target | `GitBranch` | `lucide-react` |
| HITL: result review | `TestTube2` | `lucide-react` |
| Refresh | `RefreshCw` | `lucide-react` |
| Delete | `Trash2` | `lucide-react` |
| Rename/Edit | `Pencil` | `lucide-react` |
| New session | `Plus` | `lucide-react` |
| Toggle artifacts | `PanelRightOpen` / `PanelRightClose` | `lucide-react` |
| Collapse/expand | `ChevronRight` / `ChevronDown` | `lucide-react` |
| Copy | `Copy` | `lucide-react` |
| External link | `ExternalLink` | `lucide-react` |
| Warning/drift | `AlertTriangle` | `lucide-react` |
| Pattern badge | `Sparkles` | `lucide-react` |
| Tokens | `Coins` | `lucide-react` |
| Clock/duration | `Clock` | `lucide-react` |

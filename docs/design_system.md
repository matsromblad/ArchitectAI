# AI Nightingale — Design System

This document outlines the clinical, modern UI and architectural design system for the AI Nightingale platform.

## Color Palette

The system relies on a light, professional color scheme intended for healthcare planning environments.

### Core Variables
- **Background 1 (`--bg`)**: `#F8F9FA` — The main application background. Soft, off-white to reduce eye strain.
- **Background 2 (`--bg-2`)**: `#FFFFFF` — Primary surface color for cards, sidebars, and panels.
- **Background 3 (`--bg-3`)**: `#F1F3F5` — Interactive hover states or secondary grouping.
- **Primary Accent (`--gold`)**: `#BEB1A4` (Warm beige/clay) — The main identity color, providing a natural, organic touch amidst the clinical whites.
- **Border (`--border`)**: `rgba(0,0,0,0.08)` — Very subtle borders for segmenting UI.

### Semantic Colors
- **Text Primary (`--text`)**: `#212529`
- **Text Secondary (`--text-muted`)**: `#495057` 
- **Text Tertiary (`--text-dim`)**: `#868E96`
- **Success/Working (`--success`)**: `#40C057` — Used when agents are actively working or validations pass.
- **Danger/Blocked (`--danger`)**: `#FA5252` — Used for pipeline crashes, QA rejections, or critical errors.

## Typography
- **Primary Display**: `Inter, system-ui, sans-serif`
- **Terminal/Data**: `Courier New, monospace` — Used for live logs, agent readouts, and raw data outputs to convey "machine status".

## Dashboard Avatars & Animation
- Avatars are rendered purely in a pixelated 2D canvas representation.
- **Idle State**: Agents reside in the "Lounge/Waiting Area" at the bottom left section of the virtual workspace when `status === 'waiting'`.
- **Working State**: Agents move to their respective `<node>` based on their discipline.
- **PM Agent**: Remains stationary in the "Meeting Room" (`isMeeting: true`) as a central coordinator.

## Data Visualization
- **Boxes**: Corners should be rounded (`12px` for main containers, `6px` for small cards).
- **Shadows**: Kept flat with subtle borders. Deep shadows are reserved for interactive elements only.

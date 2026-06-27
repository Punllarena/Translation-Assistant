# Translation Assistant UI Modernization Specification

**Version:** 1.0  
**Framework:** PySide6  
**Target Theme:** Modern Desktop Application (VSCode / Obsidian / JetBrains inspired)

---

# Goals

The UI redesign aims to improve:

- Visual hierarchy
- Workspace readability
- Translator workflow
- Modern desktop aesthetics
- Efficient use of screen space
- Reduced cognitive load

The redesign should **not** alter existing functionality unless specified.

---

# Design Principles

## Prioritize the Translator

The interface should clearly guide the user through the translation process.

Workflow:

```
Context
    ↓
Current Japanese Sentence
    ↓
Machine Translation (Reference)
    ↓
Human Translation
    ↓
Dictionary / Parser
```

---

## Reduce Visual Noise

Current UI issues:

- Too many borders
- Every panel has equal visual importance
- Excessive separators
- Little whitespace

Instead use:

- Cards
- Padding
- Typography
- Accent colors

rather than borders.

---

# Layout Changes

## 1. Primary Workspace Layout

Replace the current equally-weighted panels with a translator-focused workspace.

Suggested layout:

```
+--------------------------------------------------------------+
| Toolbar                                                      |
+------------------------------+-------------------------------+
| Context Above                | Machine Translation           |
|                              |-------------------------------|
|                              | Dictionary / Parser           |
|------------------------------|                               |
| Current Japanese Sentence    |                               |
|------------------------------|-------------------------------|
| Human Translation Editor                                     |
|                                                              |
|--------------------------------------------------------------|
| Context Below                                               |
+--------------------------------------------------------------+
```

---

## 2. Emphasize the Current Sentence

Increase visual importance.

### Requirements

- Larger font
- More padding
- Center of the workspace
- Easy to locate

Suggested font:

- 18–22px

---

## 3. Increase Translation Editor Size

The user's translation editor should become the largest editable area.

Reason:

Users spend the majority of their time here.

---

## 4. Reduce Context Height

Current context consumes significant space.

New behavior:

- Show approximately 2–5 previous entries
- Allow scrolling
- Optional collapse

---

# Panel Design

## Replace Framed Panels with Cards

Current:

```
--------------------
Current Sentence
--------------------
```

New:

```
╭────────────────────────────╮
 Current Sentence
──────────────────────────────
語彙がなくなる美しさだ。
╰────────────────────────────╯
```

### Card Style

- Border Radius: 6–8px
- Padding: 12px
- Thin outline
- Slightly lighter background
- Optional subtle shadow

---

## Remove Nested Borders

Avoid borders inside borders.

Use spacing instead.

---

# Toolbar Redesign

Group related controls.

Current controls:

- Translate All
- Source Language
- Target Language
- Clipboard
- History

Proposed layout:

```
[ Translate ]

Japanese ▼   →   English ▼

☑ Clipboard

◀ Previous     History     Next ▶
```

### Improvements

- Group related actions
- Consistent spacing
- Icon support

---

# Dictionary Section

Current:

```
MeCab | JParser
```

displayed side-by-side.

Replace with:

## Option A (Preferred)

Tabbed interface.

```
+-----------------------------------+
| MeCab | JParser | JMdict | AI     |
+-----------------------------------+
```

## Option B

Sidebar selection.

```
Dictionary

○ MeCab

○ JParser

○ JMdict
```

Reason:

Users usually inspect one parser at a time.

---

# Machine Translation Panel

Treat as reference material rather than editor.

Display:

```
Machine Translation

It's a beauty born of dwindling vocabulary.

[ Copy ]
```

Requirements:

- Read-only
- Minimal controls
- Optional copy button

---

# Context Display

Replace boxed text blocks with conversation-style history.

Example:

```
Previous

「あ、あの…」

"No..."

──────────────

(Current)

語彙がなくなる美しさだ。

──────────────

Next

...
```

Benefits:

- Easier dialogue tracking
- More natural reading flow

---

# Typography

## Window

13px

---

## Section Headers

14–15px

SemiBold

---

## Japanese Text

18–22px

High contrast

---

## Translation

16px

---

## Dictionary

13px

Monospace optional

---

# Color Palette

Maintain a mostly neutral theme.

Accent color should be used sparingly.

Accent color applies to:

- Translate button
- Active tab
- Selection
- Current sentence title
- Interactive controls

Avoid multiple competing accent colors.

---

# Spacing System

Use consistent spacing throughout.

## Internal Padding

8–12px

---

## Between Controls

12px

---

## Between Major Sections

16–24px

---

## Window Margins

16–24px

---

# Icons

Replace text-only controls where appropriate.

Examples:

Translate

📄

Clipboard

📋

History

🕘

Previous

◀

Next

▶

Use Material Symbols or QtAwesome.

---

# Status Bar

Current:

```
55%
1219 Words
Autosave
```

Proposed:

```
Page 206 / 365

Words: 1219

Today's Characters: 61

✓ Autosaved 1 minute ago
```

Use separators between items.

---

# Optional Features

## Collapsible Panels

Allow collapsing:

- Context Above
- Context Below
- Dictionary
- Machine Translation

Example:

```
▶ Context Above

▼ Dictionary

▶ Machine Translation
```

---

## Word Highlighting

Future enhancement.

Clicking a Japanese word should:

- Highlight the token
- Show parser information
- Show dictionary definition
- Show frequency information

Example:

```
語彙      noun

が        particle

なくなる verb

美しさ    noun

だ        copula
```

---

## Syntax Coloring

Optional.

Different colors for:

- Nouns
- Verbs
- Particles
- Adjectives
- Auxiliary verbs

Must remain subtle.

---

# Visual Style

Inspired by:

- VSCode
- Obsidian
- JetBrains IDEs
- Zed Editor
- Notion Desktop

Characteristics:

- Flat UI
- Rounded cards
- Soft contrast
- Spacious layout
- Minimal borders
- Strong typography

---

# Out of Scope

This redesign does **not** include:

- Translation engine changes
- AI functionality
- OCR improvements
- Parser improvements
- Performance optimization
- File management changes

---

# Implementation Priority

## Phase 1 (High Priority)

- [ ] New workspace layout
- [ ] Card-based panels
- [ ] Larger current sentence
- [ ] Larger translation editor
- [ ] Toolbar redesign
- [ ] Improved spacing
- [ ] Typography improvements

---

## Phase 2 (Medium Priority)

- [ ] Tabbed dictionary
- [ ] Conversation-style context
- [ ] Read-only machine translation panel
- [ ] Updated status bar
- [ ] Icon integration

---

## Phase 3 (Low Priority)

- [ ] Collapsible panels
- [ ] Word highlighting
- [ ] Syntax coloring
- [ ] Additional animations
- [ ] Theme customization

---

# Success Criteria

The redesign is successful when:

- The user's eyes naturally follow:
  - Context → Japanese → Translation → Dictionary
- The translation editor becomes the primary workspace.
- Visual clutter is significantly reduced.
- Related controls are grouped logically.
- Important information stands out through spacing and typography rather than borders.
- The application feels like a purpose-built translation workspace instead of a generic multi-panel editor.

# Translation Assistant — Feature List

Desktop app (PySide6) for translating Japanese web novels line-by-line. Basis for web app redesign.

## Core translation workflow
- Side-by-side line-by-line translation editor: source paragraph shown, user types translation below
- Keyboard-driven navigation between lines/paragraphs (all keys routed through one handler)
- Auto-copy current source line to clipboard (debounced, 400 ms) for use with external MT tools
- Machine translation aggregator panel alongside the editor
- Autosave with configurable interval; progress indicator per document
- Go-to-line, adjustable font size, always-on-top mode

## Documents & series
- Documents stored in SQLite (no loose files); document picker dialog replaces file dialogs
- Series grouping: manage series, per-series URL, drag-drop chapter reorder, renumber by title
- Batch operations: new series creation, batch import from files/folder, batch fetch
- Import/export legacy TXT format; export Markdown (plain translation or ruby-annotated)
- Per-series Markdown export; database backup export/import

## Translation memory & phrases
- Translation memory panel (previously translated lines)
- Phrase glossary: add phrases, per-series phrase suggestions, CSV phrase import
- Japanese text highlighting; spellcheck of translations (enchant/hunspell) with suggestions

## Content acquisition & publishing
- Scraper for syosetu.com: fetch single chapters or whole series in background threads
- Publish translated chapter directly to WordPress (configurable WP settings)

## Organization & stats
- User profiles (separate settings/data per profile), first-run setup wizard
- Usage statistics dialog with activity heatmap
- History log (JSONL) of work sessions
- Keyboard shortcuts reference dialog

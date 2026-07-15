# Ollama Eager Prefetch — Design

Date: 2026-07-15
Status: Approved

## Goal

While the user is idle after the current line's Ollama translation finishes,
pre-translate the next N document lines in the background and store the
results (translation + thinking trace) in the aggregator's MT cache, so
advancing to the next line shows an instant "✓ cached" result.

## Config

Two new fields on `TranslatorConfig` (`ta/config/settings.py`), used only by
the ollama entry:

- `prefetch_count: int = 0` — lines to prefetch ahead; `0` disables prefetch.
- `prefetch_idle_ms: int = 3000` — idle delay after the foreground line
  finishes before prefetch starts.

Parsed in `Settings._from_dict`, written in `Settings.save()`. Settings
dialog ollama section gains two spinboxes: "Prefetch lines ahead" (0–20) and
"Prefetch idle delay (s)".

## Queue source

`TranslationAssistantWidget` (`translation_assistant/ui/main_widget.py`)
gains a signal `upcoming_sentences_changed = Signal(list)`, emitted wherever
`source_sentence_changed` is emitted (document load and
`_update_ui_for_pointer`). Payload: up to 20 upcoming content lines after the
current pointer, each transformed exactly like the displayed line —
`replace_and_parse(raw, glossary, parse_chars)[0].lstrip("%$").strip()` —
skipping blank/non-content lines. Lines that already have a human translation
are still included.

`CombinedMainWindow` wires it to `AggregatorWidget.set_prefetch_queue(list)`.

## Prefetch engine (AggregatorWidget)

A second `OllamaTranslator` instance (`_ollama_prefetcher`) built from the
same config, with **no panel attached** — prefetch is fully silent and
cache-only. Built only when ollama is enabled and `prefetch_count > 0`.

State: `_prefetch_queue: list[str]` (raw sentences from TA),
`_prefetch_idle: QTimer` (single-shot, `prefetch_idle_ms`),
`_prefetch_chunks: list[str]`, `_prefetch_thinking: list[str]`,
`_prefetch_key: tuple[str, Language, Language] | None`,
`_prefetch_done: int` (lines completed this idle cycle).

Flow:

1. Foreground line finishes (`_on_ollama_ready`) **or** cache hit in
   `_on_translate` → reset `_prefetch_done`, start idle timer.
2. Any `_on_translate` → halt prefetcher, stop idle timer. Ollama serves one
   request at a time; the foreground request must never queue behind a
   prefetch.
3. Idle timeout → `_fire_prefetch()`: walk `_prefetch_queue`, preprocess each
   item via existing `_preprocess` (so cache keys match `_on_translate`
   exactly), pick the first whose `(text, src, dst)` key is not in
   `_mt_cache`, send to the prefetcher. Languages read at fire time.
4. Prefetcher `translation_ready` → cache `(translation, thinking)` under
   `_prefetch_key`, increment `_prefetch_done`, immediately chain to the next
   uncached item while `_prefetch_done < prefetch_count`.
5. Nothing uncached in range, or count reached → stop; wait for the next
   idle cycle.

## Thinking trace caching

`_mt_cache` value type changes from `str` to `tuple[str, str]` —
`(translation, thinking)`.

- Foreground: aggregator accumulates `translation_thinking` chunks alongside
  `translation_chunk` (cleared on `translation_started`); `_on_ollama_ready`
  caches both.
- Prefetcher: same accumulation on its own signal connections.
- `TranslationPanel.show_result()` gains `thinking: str = ""`: when
  non-empty, populate the thinking box and show the toggle collapsed
  ("Thinking (N lines)"); when empty, clear/hide as today.
- History-seeded cache entries (`_seed_mt_cache`): history stores only
  translation strings, so thinking is `""`. History format unchanged.

## Out of scope (add later if wanted)

- Status hint in the UI ("prefetching 2/5").
- History writes for prefetched lines (cache hits already skip history).
- Persisting prefetch results beyond the existing history seeding.

## Testing

- Settings roundtrip: new fields parse from TOML and survive `save()`.
- Panel: `show_result` with thinking populates box + collapsed toggle;
  without thinking hides it.
- Aggregator (stub/fake translator): idle timer fire sends first uncached
  queue item; ready caches `(text, thinking)`; navigation halts prefetcher
  and stops the timer; chaining respects `prefetch_count`; cache-hit path
  passes cached thinking to the panel.
- TA widget: `upcoming_sentences_changed` payload contents (content lines
  only, transformed, capped at 20).

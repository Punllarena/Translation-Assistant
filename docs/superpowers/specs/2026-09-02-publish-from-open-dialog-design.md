# Publish / Schedule WordPress posts from the Open Document dialog

**Date:** 2026-09-02
**Status:** Approved design — ready for implementation plan
**Approach:** A (extract a shared Qt publish-flow helper; add single + batch entry points to `OpenDocumentDialog`)

## Goal

Publish or schedule a chapter to WordPress from `OpenDocumentDialog`
(`ui/dlg_open.py`) without first opening it in the editor. Two entry points:

1. **Single chapter** — context-menu "Publish to WordPress…" on one selected
   row. Same confirm dialog and behaviour as today's `File ▸ Publish to
   WordPress…`.
2. **Batch** — with 2+ rows selected, "Publish / Schedule N Chapters…" opens a
   small dialog (start date/time, chapters-per-day, publish-now vs schedule),
   then publishes the selected chapters in `series_order` sequence, stepping the
   schedule date between them, and shows a pass/fail summary.

## Current state

All publishing lives in `TranslationAssistantWidget._on_publish_wp()`
(`ui/main_widget.py`, ~220 lines) and its `_on_publish_done` /
`_on_publish_error` callbacks. It is bound to `self._doc_id`,
`self.action_publish_wp`, `self._update_wp_status_label()`, and worker objects
stored on `self`. It inlines:

- endpoint/API-key gating → `WPSettingsDialog`
- series-slug / short-title gating → `SeriesManagerDialog`
- job prep — `db.get_document`, `db.get_series_wp_meta`,
  `db.get_lines`, `db.get_document_images`, `imageopt.shrink_image` on inline +
  cover images, "nothing translated" guard
- password fields — `db.get_series_wp_password_settings`,
  `resolve_wp_password_enabled`, `compute_password_fields`
- previous-chapter-scheduled warning — `db.get_wp_status_by_series_position`
- a hand-built confirm `QDialog`: cached WP-status line, async
  `_StatusCheckWorker` refresh, "Schedule for later" checkbox + `QDateTimeEdit`,
  auto-schedule pre-fill via `compute_auto_schedule` +
  `db.get_wp_dates` when the previous chapter is scheduled
- `build_payload` → `_PublishWorker` → `publish`
- `_on_publish_done`: `db.set_document_wp_status`, result dialog with
  page/post links, generated password, unlock notice

`wp_publisher.py` (Qt-free, 68 tests) already exposes every pure function
needed: `build_payload`, `build_chapter_body`, `compute_password_fields`,
`resolve_wp_password_enabled`, `compute_auto_schedule`, `check_status`,
`publish`, `normalize_endpoint_url`, `WPPublishError`. **No change to
`wp_publisher.py`.**

Existing UI test coverage that must stay green (`tests/test_main_window.py`):
`TestPublishWpConfirmCopy`, `build_payload` spy tests (~L1409, ~L1636),
`TestOnPublishDone`. `tests/test_combined_window.py::TestPublishWPAction`
checks the File-menu action still exists.

## Design

### 1. New module `translation_assistant/ui/wp_publish_flow.py`

Holds the shared, caller-agnostic publish machinery. Imports Qt (dialogs +
`QThread`). Everything keys off a `db`, a `settings`, and a `doc_id` — never
`self`.

#### Worker threads (moved verbatim from `main_widget.py`)

Move `_PublishWorker` and `_StatusCheckWorker` here as **public** names
`PublishWorker`, `StatusCheckWorker`. `main_widget.py` re-imports them:

```python
from translation_assistant.ui.wp_publish_flow import (
    PublishWorker as _PublishWorker,
    StatusCheckWorker as _StatusCheckWorker,
)
```

Keeps the `test_main_window.py` monkeypatch target
`translation_assistant.ui.main_widget._PublishWorker` valid.
`_IllustrationsPublishWorker` stays in `main_widget.py` (volume-illustrations
flow is out of scope).

#### `ensure_wp_config(settings, parent) -> tuple[str, str] | None`

Returns `(endpoint_url, api_key)` or `None` if the user cancels. Pops
`WPSettingsDialog` when either is blank. Lifted from the top of `_on_publish_wp`.

#### `ensure_series_wp_meta(db, settings, series_title, parent) -> dict | None`

Returns the `series_wp_meta` dict once `series_slug` and `series_title_short`
are both set; pops `SeriesManagerDialog` (with `remember_dialog_geometry`)
otherwise; `None` if still unset after the dialog. Lifted from the
mid-`_on_publish_wp` block.

#### `@dataclass PublishJob`

Immutable per-chapter prep produced by `build_job()`:

```
doc_meta, series_meta            : dict
lines                            : list[dict]
inline_images, cover_image       : list[dict] / dict | None
password, unlock_chapter_index   : str | None / int | None
prev_wp_chapter_index            : int | None   # from get_document_wp_status → wp_chapter_index
series_order, chapter_title      : convenience copies
```

#### `build_job(db, settings, doc_id) -> PublishJob`

Pure orchestration, no dialogs. Steps, in order, exactly as `_on_publish_wp`
does today:

1. `doc_meta = db.get_document(doc_id)`; `series_meta =
   db.get_series_wp_meta(doc_meta["series_title"])`.
2. Password: `pw = db.get_series_wp_password_settings(series_title)`;
   `enabled = resolve_wp_password_enabled(pw, settings.wp_password_enabled)`;
   `unlock_after = pw["wp_unlock_after"] if pw["wp_unlock_after"] != -1 else
   settings.wp_unlock_after`; if `enabled`,
   `password, unlock_chapter_index = compute_password_fields(series_order,
   unlock_after)` else `(None, None)`.
3. `lines = db.get_lines(doc_id)`.
4. Images: `imgs = db.get_document_images(doc_id)`;
   `inline = [i for i in imgs if not i["is_cover"] and not
   i["exclude_export"]]`; `cover = next((i for i in imgs if i["is_cover"]),
   None)`; run `imageopt.shrink_image` on each (inline + cover), rewriting
   `src_path` ext to `.jpg` when shrunk — copy of the current loop.
5. `prev_wp_chapter_index =
   db.get_document_wp_status(doc_id).get("wp_chapter_index")`.
6. Return the `PublishJob`.

Raises `PublishJobError` (new, local) with a user-facing message when there is
nothing to publish (`not any(ln["translated_text"].strip() for ln in lines)`).
Slug/short-title validation stays in `build_payload` (already raises
`ValueError`); callers surface it.

#### `job_to_payload(job, api_key, *, scheduled_date, attribution) -> dict`

Thin wrapper over `wp_publisher.build_payload` that maps `PublishJob` fields to
kwargs (`images=job.inline_images`, `cover=job.cover_image`,
`previous_chapter_index=job.prev_wp_chapter_index`, …). Central so single and
batch build identical payloads.

#### `PublishConfirmDialog(QDialog)`

The current hand-built confirm dialog, parameterised by `(job, db, settings,
endpoint_url, api_key, parent)`. Owns:

- cached status line + async `StatusCheckWorker` refresh (started in `__init__`,
  `quit()/wait(500)` in `done()`), writing back via `db.set_document_wp_status`
  as today
- previous-chapter-scheduled warning (uses
  `db.get_wp_status_by_series_position`)
- "Schedule for later" checkbox + `QDateTimeEdit`, default-time pre-fill from
  `settings.wp_default_schedule_time`, auto-schedule pre-fill via
  `compute_auto_schedule` + `db.get_wp_dates` +
  `settings.wp_schedule_scope_global` when the previous chapter is scheduled
- `.scheduled_date_utc() -> str | None` — the `"%Y-%m-%dT%H:%M:%SZ"` string, or
  `None` when the box is unchecked

No behaviour change vs today; this is a straight extract-to-class.

#### `PublishResultDialog(...)` / `show_publish_result(result, job, scheduled_date, parent) -> None`

The `_on_publish_done` result dialog (page/post links, password field, unlock
notice). Takes plain args, no `self`.

#### `run_single_publish(db, settings, doc_id, parent, *, on_status_changed=None) -> None`

Glue that reproduces today's end-to-end flow for one doc:

1. `cfg = ensure_wp_config(settings, parent)` → return on `None`.
2. `series_meta = ensure_series_wp_meta(...)` → return on `None`.
3. `job = build_job(...)`; on `PublishJobError` show `QMessageBox.warning` and
   return.
4. `dlg = PublishConfirmDialog(...)`; `if not dlg.exec(): return`.
5. `payload = job_to_payload(job, api_key,
   scheduled_date=dlg.scheduled_date_utc(),
   attribution=settings.wp_attribution_enabled)`; on `ValueError` warn + return.
6. Start `PublishWorker`; on success →
   `db.set_document_wp_status(...)` (status `future` if scheduled else
   `publish`), `show_publish_result(...)`, call `on_status_changed()` if given;
   on error → `QMessageBox.warning`.

The worker and dialog are parented to `parent` so they outlive the function;
store them on `parent` via a private attr list (e.g.
`parent._wp_flow_keepalive`) to avoid GC — documented in the module.

### 2. `main_widget.py` refactor

`_on_publish_wp` becomes:

```python
def _on_publish_wp(self) -> None:
    from translation_assistant.ui.wp_publish_flow import run_single_publish
    run_single_publish(
        self._db, self._settings, self._doc_id, self,
        on_status_changed=self._update_wp_status_label,
    )
```

Delete the moved worker classes (replace with the re-import shim above). Keep
`_on_publish_done` / `_on_publish_error`? — no; their bodies move into
`wp_publish_flow`. Any test calling `win._on_publish_done(...)` directly
(`TestOnPublishDone`) is updated to call
`wp_publish_flow.show_publish_result(...)` plus an explicit
`db.set_document_wp_status(...)`, or a new thin `_on_publish_done` kept as a
1-line delegator if that is materially less churn — implementer's call, decided
during TDD.

### 3. `dlg_open.py` — single-chapter entry

In `_on_chapter_context_menu`, after the Delete separator:

```python
act_publish = menu.addAction("Publish to WordPress…")
act_publish.setEnabled(len(merge_ids) == 1 and self._settings is not None)
act_publish_batch = menu.addAction("Publish / Schedule Chapters…")
act_publish_batch.setEnabled(len(merge_ids) >= 2 and self._settings is not None)
```

Dispatch:

```python
elif chosen == act_publish:
    from translation_assistant.ui.wp_publish_flow import run_single_publish
    run_single_publish(
        self._db, self._settings, merge_ids[0], self,
        on_status_changed=lambda: self._load_chapters(self._current_series_raw()),
    )
elif chosen == act_publish_batch:
    self._on_publish_batch(merge_ids)
```

`_settings` is already an optional ctor arg and the live launcher
(`main_widget.py:1125`) already passes `settings=self._settings`, so no
call-site change is needed (`main_window.py` is legacy/not launched — ignore
it). The `_settings is not None` guard on the menu items covers any future
call site that omits it. After publish the tree row refreshes via
`_load_chapters`, matching the post-merge / post-split pattern.

### 4. `dlg_open.py` — batch dialog

New `_BatchPublishDialog(QDialog)` in `dlg_open.py` (private, like
`_SplitChapterDialog`). Inputs:

- read-only list of the selected chapters, ordered by `series_order`
  (`#`, title, current WP cell)
- **Schedule** checkbox (default on). Unchecked ⇒ every chapter published
  immediately, no `publish_date`.
- **Start** `QDateTimeEdit` — first chapter's slot; default = today at
  `settings.wp_default_schedule_time` (or now + 1h), bumped a day if already
  past. Disabled when Schedule is off.
- **Chapters per day** `QSpinBox`, default `settings.wp_chapters_per_day`
  (min 1). Disabled when Schedule is off.
- OK / Cancel.

`_on_publish_batch(doc_ids)`:

1. `cfg = ensure_wp_config(self._settings, self)` → return on `None`.
2. Group `doc_ids` by `series_title`; for each distinct series
   `ensure_series_wp_meta(...)` → abort the whole batch on `None` (message names
   the series).
3. Sort `doc_ids` by `(series_title, series_order)`.
4. `dlg = _BatchPublishDialog(...)`; `if not dlg.exec(): return`.
5. Compute schedule slots (only if Schedule on): `assigned: list[str] = []`;
   first slot = the dialog's Start (→ UTC string); each subsequent =
   `compute_auto_schedule(assigned[-1], assigned, chapters_per_day,
   settings.wp_default_schedule_time)` → UTC string. One scheduling algorithm,
   shared with the single-chapter auto-fill.
6. Run sequentially on a `_BatchPublishWorker(QThread)` that, per chapter:
   `job = build_job(db, settings, doc_id)` →
   `payload = job_to_payload(job, api_key, scheduled_date=slot,
   attribution=settings.wp_attribution_enabled)` →
   `wp_publisher.publish(endpoint_url, payload)` →
   emits `progress(i, n, doc_id, result | error_str)`.
   `PublishJobError` / `ValueError` / `WPPublishError` for one chapter are
   caught, recorded as a failure, and the loop continues.
7. A `QProgressDialog` shows "Publishing chapter X of N"; Cancel stops after the
   in-flight chapter.
8. On finish, for each success `db.set_document_wp_status(doc_id, "future" if
   scheduled else "publish", post_url, wp_date, series_order)`, then
   `self._load_chapters(...)` and a summary `QDialog`: per-chapter ✓/✗ with the
   error or the scheduled date, and any generated passwords
   (chapter → password) in a read-only multiline field.

`build_job` reads a fresh DB row per chapter, so image shrinking and password
generation happen lazily inside the worker — no giant up-front payload in
memory for a 30-chapter volume.

## Data flow

```
context menu / File menu
  └─ run_single_publish / _on_publish_batch
       ├─ ensure_wp_config ........... WPSettingsDialog        (settings)
       ├─ ensure_series_wp_meta ...... SeriesManagerDialog     (db, settings)
       ├─ build_job (per doc) ........ db.get_document/_lines/_images,
       │                               imageopt.shrink_image,
       │                               compute_password_fields
       ├─ confirm / batch dialog ..... compute_auto_schedule, db.get_wp_dates,
       │                               StatusCheckWorker (single only)
       ├─ job_to_payload ............. wp_publisher.build_payload
       ├─ PublishWorker / _BatchPublishWorker → wp_publisher.publish
       └─ on success ................. db.set_document_wp_status,
                                       result / summary dialog,
                                       on_status_changed()  (refresh caller UI)
```

## Error handling

| Condition | Behaviour |
|---|---|
| endpoint / API key blank, user cancels `WPSettingsDialog` | abort silently |
| `series_slug` / short title unset after `SeriesManagerDialog` | abort, no publish |
| no translated lines (`PublishJobError`) | `QMessageBox.warning`, that chapter skipped (batch continues) |
| `build_payload` `ValueError` (missing slug) | warn; single aborts, batch records failure |
| `WPPublishError` from `publish` | single: `QMessageBox.warning`; batch: record failure, continue |
| `publish` HTTP 409 (already published) | unchanged — `wp_publisher.publish` returns the parsed body, treated as "already published" |
| batch: user hits Cancel | finish in-flight chapter, then show summary of what completed |
| previous chapter still `future` | single: existing inline warning + "Publish Anyway"; batch: summary note, does not block |

## Testing

New `tests/test_wp_publish_flow.py`:

- `build_job`: happy path (asserts lines/images/password fields populated);
  images shrunk + `.jpg` rewrite; cover separated from inline;
  `exclude_export` images dropped; `PublishJobError` on all-empty translation;
  password `None` when disabled, present when enabled with
  `series_order > unlock_after`.
- `job_to_payload`: forwards `images` / `cover` / `previous_chapter_index` /
  `scheduled_date` / `attribution` into `build_payload` (spy).
- batch schedule slot computation: N chapters, `chapters_per_day = k` ⇒ first k
  share the start day, slot k+1 rolls to next day at `wp_default_schedule_time`
  (drive `compute_auto_schedule` directly with the assembled `assigned` list).
- `_BatchPublishWorker`: monkeypatch `wp_publisher.publish`; one chapter raising
  `WPPublishError` ⇒ `progress` still emitted for the rest, failure recorded.

`tests/test_dlg_open.py`:

- context menu shows "Publish to WordPress…" enabled for exactly one selection,
  disabled for zero / 2+; batch item mirror-image.
- `run_single_publish` invoked with `(db, settings, <selected doc_id>, dlg,
  …)` — monkeypatch the function, assert args.
- `_on_publish_batch`: monkeypatch `_BatchPublishDialog` to auto-accept and
  `wp_publisher.publish` to succeed; assert `db.set_document_wp_status` written
  for every selected doc and `_load_chapters` re-run.

`tests/test_main_window.py`: update the 3 groups noted above to the moved
symbols; `_on_publish_wp` test (`TestPublishWpConfirmCopy`) now drives
`PublishConfirmDialog` (monkeypatch `PublishWorker`).

`tests/test_combined_window.py::TestPublishWPAction`: unchanged — the File-menu
action stays.

Full suite (`pytest`) green.

## Out of scope

- Volume-illustrations publish (`_on_publish_volume_illustrations`,
  `_IllustrationsPublishWorker`) — stays in `main_widget.py`.
- Any change to `wp_publisher.py` or the WP server plugin.
- Removing the `File ▸ Publish to WordPress…` menu action (approach C).
- Retry / resume of a partially-failed batch — the summary lists failures; the
  user re-selects and re-runs.
- Per-chapter password-protection overrides in the batch dialog — uses the
  resolved series/global setting, same as single.

## File-by-file change list

| File | Change |
|---|---|
| `translation_assistant/ui/wp_publish_flow.py` | **new** — workers, `ensure_wp_config`, `ensure_series_wp_meta`, `PublishJob` + `build_job` + `PublishJobError`, `job_to_payload`, `PublishConfirmDialog`, `show_publish_result`, `run_single_publish` |
| `translation_assistant/ui/main_widget.py` | `_on_publish_wp` → 3-line delegator; delete moved worker classes + re-import shim; fold `_on_publish_done/_error` into the helper |
| `translation_assistant/ui/dlg_open.py` | 2 context-menu items + dispatch; `_on_publish_batch`; `_BatchPublishDialog`; `_BatchPublishWorker` |
| `tests/test_wp_publish_flow.py` | **new** |
| `tests/test_dlg_open.py` | new context-menu + dispatch tests |
| `tests/test_main_window.py` | retarget moved symbols in 3 test groups |

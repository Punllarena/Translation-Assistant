# Volume Rename Merge Guard — Design Spec

**Goal:** Prevent `_EditVolumeMetadataDialog` (added in the edit-volume-metadata feature) from silently merging two distinct volumes when a user renames one volume's title to match another's. Instead, detect the collision, confirm with the user, and — if confirmed — merge deliberately and atomically with well-defined metadata resolution.

**Background:** `Database.update_volume_metadata(series_title, volume_title, *, new_volume_title, volume_author, volume_illustrator, volume_publisher, volume_identifier)` bulk-updates every `documents` row matching `(series_title, volume_title)`, including moving them to `new_volume_title`. If `new_volume_title` happens to equal another existing volume in the same series, both volumes' rows end up sharing one `volume_title` with no warning — a silent, irreversible merge with inconsistent per-row metadata (the renamed-in rows get the dialog's values; the original target volume's rows keep whatever they had).

**Out of scope:** This spec does not change `volume_title`'s meaning or add a `volume_index` column. `volume_title` remains the literal display/export title (it is passed directly as the EPUB's `dc:title` in `main_widget.py:1311`). A future `volume_index INTEGER` column is a likely **prerequisite** for two related, separately-specced features — showing which volume a chapter belongs to in the Open dialog (sorted correctly), and expressing volume separation in the WordPress table of contents — since `volume_title` text alone isn't reliably sortable. Not needed here.

## Global Constraints

- Never import `sqlite3` outside `db.py`.
- Case-sensitive exact match for `volume_title` comparisons, consistent with existing behavior (no `COLLATE NOCASE` used elsewhere for this column).
- Series is fixed for the whole `_EditVolumeMetadataDialog` session — cross-series collisions are impossible by construction, no check needed.
- The existing blank-`volume_title` guard (Save rejects empty) already prevents `new_volume_title=""` from ever reaching the collision check.

## Data Flow

1. User edits volume metadata in `_EditVolumeMetadataDialog`, changes Volume Title, clicks Save (dialog's own blank-check already passed).
2. `_on_edit_volume` (dlg_open.py) has the accepted dialog's values. If `dlg.volume_title != old_volume_title` (the doc's current volume_title before edit):
   - Call `db.get_document_ids_by_volume(series_title, dlg.volume_title)`.
   - Non-empty result → collision. Show a confirmation dialog (see UX below).
     - User cancels → abort the whole edit silently (no DB write), same as closing the dialog. User can re-open Edit Volume and pick a different name.
     - User confirms → proceed to `_do_edit_volume(..., merge=True)`.
   - Empty result → no collision, proceed to `_do_edit_volume(..., merge=False)` (today's behavior, unchanged).
3. `_do_edit_volume` passes `merge` through to `db.update_volume_metadata(..., merge=merge)`.
4. In `db.py`, `update_volume_metadata` gains `merge: bool = False`:
   ```sql
   -- merge=False (default, unchanged):
   UPDATE documents SET volume_title=?, volume_author=?, volume_illustrator=?,
       volume_publisher=?, volume_identifier=?
   WHERE series_title=? AND volume_title=?              -- old_volume_title only

   -- merge=True:
   UPDATE documents SET volume_title=?, volume_author=?, volume_illustrator=?,
       volume_publisher=?, volume_identifier=?
   WHERE series_title=? AND volume_title IN (?, ?)       -- old_volume_title, new_volume_title
   ```
   Single `execute` + single `commit()` either way — atomic, no two-step window where the group is half-renamed. Because the `WHERE` matches both old and new titles in one statement, every row ends up with the dialog's metadata values applied ("overwrite target with dialog values" — the merged group is left fully consistent, not a mix of old and new field values).

## Confirmation Dialog UX

Shown only when a collision is detected (the common no-rename / no-collision path never sees this).

- Chapter count for the message comes from `len(get_document_ids_by_volume(series_title, new_volume_title))` (queried before the merge, i.e. the existing target volume's size — not including the rows being renamed in).
- Message: `"'{new_volume_title}' already exists in this series with {N} chapter(s). Renaming will merge both volumes together and apply this dialog's author/illustrator/publisher/ISBN to all chapters in the merged volume. This cannot be undone. Continue?"`
- `QMessageBox.question` with Yes/No buttons, **default button = No** (destructive-leaning action).

## Edge Cases

- **Blank `new_volume_title`:** already blocked upstream by the prior Save-validation fix; the collision check never evaluates `""` as a merge target.
- **No rename, metadata-only edit** (`new_volume_title == old_volume_title`): collision check is skipped entirely — never treated as a merge candidate, matches current behavior exactly.
- **Case variants** (`"Vol 2"` vs `"vol 2"`): treated as distinct volumes (case-sensitive), consistent with the rest of the schema. Not a collision.
- **Cross-series:** impossible — the dialog is scoped to one `series_title` throughout; `new_volume_title` is only ever checked against volumes in that same series.

## Testing

- `test_update_volume_metadata_merge_combines_both_buckets` — 2 docs in volume "A", 1 doc in volume "B"; call with `merge=True`, old="A", new="B"; assert all 3 rows now have `volume_title="B"` and the passed-in metadata values.
- `test_update_volume_metadata_default_merge_false_unchanged` — regression guard confirming `merge` defaulting to `False` preserves today's scoped-to-old-title-only behavior.
- `test_do_edit_volume_detects_collision_and_prompts` — target volume exists; mock `QMessageBox.question`; assert it's shown with the correct chapter count in the message.
- `test_do_edit_volume_merge_confirmed_calls_merge_true` — mock the message box answer as Yes; assert `update_volume_metadata` is called with `merge=True`.
- `test_do_edit_volume_merge_cancelled_aborts` — mock the message box answer as No; assert `update_volume_metadata` is never called, no DB state changes.
- `test_do_edit_volume_no_collision_skips_prompt` — renaming to a genuinely new title never shows the message box, calls `update_volume_metadata` with `merge=False`.

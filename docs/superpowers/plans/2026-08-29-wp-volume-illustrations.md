# WordPress Volume Illustrations Gallery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Publish Volume Illustrations to WordPress…" menu command that gathers every illustration in the open document's volume and publishes them as one WordPress gallery page, linked from the series ToC under that volume's heading.

**Architecture:** Two repos. TA app (`wp_publisher.py` builds N batched JSON payloads under the host's ~1 MB proxy cap; `main_widget.py` gathers + shrinks images and drives a sequential worker) and the WordPress plugin (`translation-assistant-publisher` gains a `POST /wp-json/ta-publisher/v1/illustrations` route with `mode: replace|append` — `replace` creates/overwrites the gallery page and wipes its attachments, `append` adds more image blocks to it). Images are downscaled client-side by the already-in-tree `imageopt.shrink_image`.

**Tech Stack:** Python 3 + pytest + PySide6 (TA side; `wp_publisher.py` stays Qt-free). PHP 8 + WordPress plugin API (WP side, no test harness — verified with `php -l` + curl).

**Spec:** `docs/superpowers/specs/2026-08-29-wp-volume-illustrations-design.md`

## Global Constraints

- **Two repos, two working trees.** TA side: `/home/pun/workspace/TranslationAssistant-PySide6-Port`. WP side: `/home/pun/workspace/wp-dev`, plugin at `plugins/translation-assistant-publisher/`. Commit separately in each — never `git add` across them.
- **TA venv required before pytest:** `source .venv/bin/activate`.
- **The TA working tree has unrelated in-flight modifications** (`db.py`, `epub.py`, `scraper.py`, `wp_publisher.py`, `main_widget.py`, several `tests/`, plus untracked `imageopt.py` / `test_imageopt.py`). Stage only the exact files each task names. Never `git add -A` / `git commit -a`.
- **Do not modify `_on_publish_wp`** in `main_widget.py` — it carries uncommitted in-flight edits. The new handler gets its own `_ensure_wp_ready` helper rather than refactoring shared code out of `_on_publish_wp`.
- **Do not reimplement** `imageopt.shrink_image` or the `body.get("error") or body.get("message")` error-key parse — both already exist in the tree; consume them.
- **`wp_publisher.py` stays Qt-free.** All `imageopt` / PySide6 use lives in `main_widget.py`.
- **Payload size budget:** `_ILLUS_BATCH_BYTES = 800_000` bytes of base64 per request body.
- **Batch ordering is strict:** the `replace` batch must land before any `append` batch. The worker calls batches sequentially, never in parallel.
- **Plugin version bump:** every functional plugin change bumps the `Version:` header in `translation-assistant-publisher.php`. Current version is **1.5.3**; this feature ships as **1.5.4**.
- **Plugin error responses** use the JSON key `error` (not `message`) — the TA client reads `error` first.
- **`series_link` is optional** on the plugin side (EPUB-imported series send `""`), matching `tap_handle_publish` after plugin commit `a94aded`.

---

## File Structure

**TA repo:**
- Modify: `translation_assistant/wp_publisher.py` — add `_ILLUSTRATIONS_PATH`, `build_illustrations_payloads()`, `publish_illustrations()`. No change to `build_payload` / `publish`.
- Modify: `translation_assistant/ui/main_widget.py` — add `_IllustrationsPublishWorker`, `_ensure_wp_ready()`, `_on_publish_volume_illustrations()`, `_on_publish_illus_done()`, `_on_publish_illus_error()`, `action_publish_volume_illus`, and its enable/disable at the two existing sites.
- Modify: `translation_assistant/ui/combined_window.py` — one `file_menu.addAction(...)` line.
- Modify: `tests/test_wp_publisher.py` — tests for the two new `wp_publisher` functions (append; file already dirty).
- Modify: `tests/test_main_window.py` — tests for the worker + handler (append).
- Track (if still untracked): `translation_assistant/imageopt.py`, `tests/test_imageopt.py`.

**WP plugin repo:**
- Modify: `plugins/translation-assistant-publisher/translation-assistant-publisher.php` — third `register_rest_route`, `tap_handle_illustrations()`, `Version:` bump.
- Modify: `plugins/translation-assistant-publisher/includes/class-publisher.php` — `publish_illustrations()`, `build_illustrations_blocks()`.
- No new files in either repo.

---

## Task 1: Track the `imageopt` dependency

The gallery handler (Task 5) imports `translation_assistant.imageopt.shrink_image`. That module and its test are complete but currently untracked. Land them on their own so later commits stay focused. If they are already tracked when you reach this task, just run the test and skip the commit step.

**Files:**
- Track: `translation_assistant/imageopt.py`
- Track: `tests/test_imageopt.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `translation_assistant.imageopt.shrink_image(data: bytes, max_dim: int = 1600, target_bytes: int = 350_000) -> bytes` — returns a smaller JPEG rendering, or the **same** `bytes` object when the input is already under `target_bytes`, undecodable, or no re-encoding beats the original.

- [ ] **Step 1: Confirm the module and test exist**

Run: `git status --porcelain translation_assistant/imageopt.py tests/test_imageopt.py`
Expected: either two `??` lines (untracked — continue to Step 2) or no output (already tracked — run Step 3, skip Step 4).

- [ ] **Step 2: Read both files**

Read `translation_assistant/imageopt.py` and `tests/test_imageopt.py` in full. Confirm `shrink_image` has the signature in the Interfaces block above and that the module's only imports are from `PySide6`.

- [ ] **Step 3: Run the imageopt tests**

Run: `source .venv/bin/activate && pytest tests/test_imageopt.py -v`
Expected: PASS (3 tests: `test_shrink_caps_size_and_dimension`, `test_shrink_returns_same_object_when_already_small`, `test_shrink_returns_original_on_undecodable_large_blob`).

- [ ] **Step 4: Commit (only if Step 1 showed them untracked)**

```bash
git add translation_assistant/imageopt.py tests/test_imageopt.py
git commit -m "chore: track imageopt.shrink_image and its test"
```

---

## Task 2: `build_illustrations_payloads()` — batched payload builder

**Files:**
- Modify: `translation_assistant/wp_publisher.py` (add near `build_image_payload`, after line 116)
- Test: `tests/test_wp_publisher.py` (append at end of file)

**Interfaces:**
- Consumes: `_encode_image(row: dict) -> dict` (existing, `wp_publisher.py:65`) — returns `{"filename": str, "mime": str, "data_base64": str}` from a row with `src_path` and `data` keys.
- Produces:
  - `_ILLUS_BATCH_BYTES: int = 800_000` (module constant)
  - `build_illustrations_payloads(doc_meta: dict, series_meta: dict, images: list[dict], api_key: str, cover: dict | None = None) -> list[dict]`
    - `images` / `cover` rows each carry at least `src_path: str` and `data: bytes`.
    - Raises `ValueError` when `series_meta["series_slug"]` or `series_meta["series_title_short"]` is missing/falsy.
    - Returns a non-empty list. Element 0 has `"mode": "replace"` and (when `cover` is not None) a `"cover"` key. Every other element has `"mode": "append"` and no `"cover"` key. Every element has keys `api_key, series_title, series_slug, series_title_short, series_link, images, mode`, plus `volume_title` when `doc_meta["volume_title"]` is truthy. Concatenating every element's `images` (in list order) reproduces `[_encode_image(im) for im in images]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wp_publisher.py`:

```python
from translation_assistant.wp_publisher import (
    build_illustrations_payloads, _ILLUS_BATCH_BYTES,
)


def _illus_meta():
    doc_meta = {"series_title": "Sword of the Wanderer", "volume_title": "Volume 1"}
    series_meta = {
        "series_slug": "sword-of-the-wanderer",
        "series_title_short": "SotW",
        "syosetu_url": "https://ncode.syosetu.com/n1234ab/",
    }
    return doc_meta, series_meta


def _img(name, nbytes):
    return {"src_path": name, "data": b"x" * nbytes}


def test_illus_payloads_single_batch_when_small():
    doc_meta, series_meta = _illus_meta()
    out = build_illustrations_payloads(
        doc_meta, series_meta, [_img("a.png", 10), _img("b.png", 10)], api_key="K"
    )
    assert len(out) == 1
    assert out[0]["mode"] == "replace"
    assert out[0]["volume_title"] == "Volume 1"
    assert out[0]["series_link"] == "https://ncode.syosetu.com/n1234ab/"
    assert [i["filename"] for i in out[0]["images"]] == ["a.png", "b.png"]
    assert "position" not in out[0]["images"][0]


def test_illus_payloads_splits_over_budget():
    doc_meta, series_meta = _illus_meta()
    # each image base64-inflates ~4/3; make three that each blow ~half the budget
    half = int(_ILLUS_BATCH_BYTES * 0.5)
    imgs = [_img(f"{i}.png", half) for i in range(3)]
    out = build_illustrations_payloads(doc_meta, series_meta, imgs, api_key="K")
    assert len(out) >= 2
    assert out[0]["mode"] == "replace"
    assert all(p["mode"] == "append" for p in out[1:])
    seen = [i["filename"] for p in out for i in p["images"]]
    assert seen == ["0.png", "1.png", "2.png"]


def test_illus_payloads_cover_only_on_first_batch():
    doc_meta, series_meta = _illus_meta()
    half = int(_ILLUS_BATCH_BYTES * 0.5)
    imgs = [_img(f"{i}.png", half) for i in range(3)]
    out = build_illustrations_payloads(
        doc_meta, series_meta, imgs, api_key="K", cover=_img("cover.png", 10)
    )
    assert "cover" in out[0]
    assert out[0]["cover"]["filename"] == "cover.png"
    assert all("cover" not in p for p in out[1:])


def test_illus_payloads_omits_volume_title_when_blank():
    doc_meta, series_meta = _illus_meta()
    doc_meta["volume_title"] = ""
    out = build_illustrations_payloads(doc_meta, series_meta, [_img("a.png", 10)], api_key="K")
    assert "volume_title" not in out[0]


def test_illus_payloads_missing_series_link_key_ok():
    doc_meta, series_meta = _illus_meta()
    del series_meta["syosetu_url"]
    out = build_illustrations_payloads(doc_meta, series_meta, [_img("a.png", 10)], api_key="K")
    assert out[0]["series_link"] == ""


def test_illus_payloads_requires_slug_and_short_title():
    doc_meta, series_meta = _illus_meta()
    with pytest.raises(ValueError):
        build_illustrations_payloads(
            doc_meta, {"series_slug": "", "series_title_short": "X"}, [_img("a.png", 1)], api_key="K"
        )
    with pytest.raises(ValueError):
        build_illustrations_payloads(
            doc_meta, {"series_slug": "x", "series_title_short": ""}, [_img("a.png", 1)], api_key="K"
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_wp_publisher.py -k illus_payloads -v`
Expected: FAIL — `ImportError: cannot import name 'build_illustrations_payloads'`.

- [ ] **Step 3: Implement**

In `translation_assistant/wp_publisher.py`, after `build_image_payload` (line 116):

```python
_ILLUS_BATCH_BYTES = 800_000


def build_illustrations_payloads(
    doc_meta: dict,
    series_meta: dict,
    images: list[dict],
    api_key: str,
    cover: dict | None = None,
) -> list[dict]:
    """Split a volume's illustrations into per-request payloads.

    The WP host's proxy resets bodies over ~1 MB, so a volume's art cannot
    ship in one JSON POST. Element 0 carries ``mode: "replace"`` (plus the
    cover, if any); the rest carry ``mode: "append"``. Images arrive
    already downscaled by the caller (``imageopt.shrink_image``) — this
    function only groups them under ``_ILLUS_BATCH_BYTES`` of base64.
    """
    if not series_meta.get("series_slug"):
        raise ValueError("series_slug is required — set it in Series Manager")
    if not series_meta.get("series_title_short"):
        raise ValueError("series_title_short is required — set it in Series Manager")

    base = {
        "api_key":            api_key,
        "series_title":       doc_meta["series_title"],
        "series_slug":        series_meta["series_slug"],
        "series_title_short": series_meta["series_title_short"],
        "series_link":        series_meta.get("syosetu_url") or "",
    }
    if doc_meta.get("volume_title"):
        base["volume_title"] = doc_meta["volume_title"]

    enc_cover = _encode_image(cover) if cover is not None else None
    encoded = [_encode_image(im) for im in images]

    batches: list[list[dict]] = [[]]
    size = len(enc_cover["data_base64"]) if enc_cover else 0
    for e in encoded:
        b = len(e["data_base64"])
        if batches[-1] and size + b > _ILLUS_BATCH_BYTES:
            batches.append([])
            size = 0
        batches[-1].append(e)
        size += b

    payloads = []
    for i, batch in enumerate(batches):
        p = {**base, "images": batch, "mode": "replace" if i == 0 else "append"}
        if i == 0 and enc_cover is not None:
            p["cover"] = enc_cover
        payloads.append(p)
    return payloads
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_wp_publisher.py -k illus_payloads -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the full `wp_publisher` test file (no regressions)**

Run: `source .venv/bin/activate && pytest tests/test_wp_publisher.py -q`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/wp_publisher.py tests/test_wp_publisher.py
git commit -m "feat(wp): build_illustrations_payloads — batched gallery payloads"
```

---

## Task 3: `publish_illustrations()` — HTTP client for the new route

**Files:**
- Modify: `translation_assistant/wp_publisher.py` (add after `publish`, end of file)
- Test: `tests/test_wp_publisher.py` (append)

**Interfaces:**
- Consumes: `WPPublishError` (existing), the module's `_ENDPOINT_PATH = "/wp-json/ta-publisher/v1/publish"` (existing, line 245).
- Produces:
  - `_ILLUSTRATIONS_PATH: str = "/wp-json/ta-publisher/v1/illustrations"`
  - `publish_illustrations(endpoint_url: str, payload: dict, timeout: int = 20) -> dict` — POSTs `payload` as JSON to the site's `/wp-json/ta-publisher/v1/illustrations`, deriving the site root from `endpoint_url` whether it is a bare site URL or already ends in `_ENDPOINT_PATH`. Returns the parsed JSON dict on 200. Raises `WPPublishError(message, status_code)` on any `HTTPError` (message = response body's `error` key, else `message` key, else `str(exc)`) or `URLError` (`status_code=None`). No 409 special-casing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wp_publisher.py`:

```python
from translation_assistant.wp_publisher import publish_illustrations


def test_publish_illustrations_url_from_bare_site():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        m = MagicMock()
        m.__enter__ = lambda s: s
        m.__exit__ = MagicMock(return_value=False)
        m.read.return_value = json.dumps({"status": "ok", "created": True}).encode()
        return m

    with patch("urllib.request.urlopen", fake_urlopen):
        out = publish_illustrations("https://site.com", {"mode": "replace"})
    assert captured["url"] == "https://site.com/wp-json/ta-publisher/v1/illustrations"
    assert out["created"] is True


def test_publish_illustrations_url_from_publish_endpoint():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        m = MagicMock()
        m.__enter__ = lambda s: s
        m.__exit__ = MagicMock(return_value=False)
        m.read.return_value = b'{"status": "ok"}'
        return m

    with patch("urllib.request.urlopen", fake_urlopen):
        publish_illustrations("https://site.com/wp-json/ta-publisher/v1/publish", {})
    assert captured["url"] == "https://site.com/wp-json/ta-publisher/v1/illustrations"


def test_publish_illustrations_surfaces_error_key():
    err = HTTPError("url", 400, "Bad Request", {}, None)
    err.read = lambda: b'{"error": "Missing field: images"}'
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(WPPublishError) as ei:
            publish_illustrations("https://site.com", {})
    assert ei.value.message == "Missing field: images"
    assert ei.value.status_code == 400


def test_publish_illustrations_connection_error():
    with patch("urllib.request.urlopen", side_effect=URLError("refused")):
        with pytest.raises(WPPublishError) as ei:
            publish_illustrations("https://site.com", {})
    assert ei.value.status_code is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_wp_publisher.py -k publish_illustrations -v`
Expected: FAIL — `ImportError: cannot import name 'publish_illustrations'`.

- [ ] **Step 3: Implement**

At the end of `translation_assistant/wp_publisher.py`:

```python
_ILLUSTRATIONS_PATH = "/wp-json/ta-publisher/v1/illustrations"


def publish_illustrations(endpoint_url: str, payload: dict, timeout: int = 20) -> dict:
    base = endpoint_url.rstrip("/")
    if base.endswith(_ENDPOINT_PATH):
        base = base[: -len(_ENDPOINT_PATH)]
    url = base + _ILLUSTRATIONS_PATH
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                raise WPPublishError(
                    f"Server returned non-JSON response: {body[:200]!r}", status_code=None
                )
    except HTTPError as exc:
        try:
            body = json.loads(exc.read())
            msg = body.get("error") or body.get("message") or str(exc)
        except Exception:
            msg = str(exc)
        raise WPPublishError(msg, status_code=exc.code) from exc
    except URLError as exc:
        raise WPPublishError(
            f"Could not reach {url}: {exc.reason}", status_code=None
        ) from exc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_wp_publisher.py -k publish_illustrations -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Full file, no regressions**

Run: `source .venv/bin/activate && pytest tests/test_wp_publisher.py -q`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/wp_publisher.py tests/test_wp_publisher.py
git commit -m "feat(wp): publish_illustrations HTTP client for the gallery route"
```

---

## Task 4: `_IllustrationsPublishWorker` — sequential batch sender

**Files:**
- Modify: `translation_assistant/ui/main_widget.py` (add class right after `_PublishWorker`, ~line 46)
- Test: `tests/test_main_window.py` (append a `TestIllustrationsWorker` class at end)

**Interfaces:**
- Consumes: `wp_publisher.publish_illustrations` (Task 3), `wp_publisher.WPPublishError` (existing).
- Produces: `_IllustrationsPublishWorker(QThread)` with:
  - `__init__(self, endpoint_url: str, payloads: list[dict], parent=None)`
  - signals `succeeded = Signal(dict)`, `error = Signal(str)`
  - `run()` calls `publish_illustrations(endpoint_url, p)` for each `p` in `payloads` **in order**; on the first `WPPublishError`/`Exception` it emits `error` with `f"batch {i+1}/{len(payloads)}: {msg}"` and stops; if all succeed it emits `succeeded` with the **first** batch's result dict.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main_window.py`:

```python
class TestIllustrationsWorker:
    def test_sends_batches_in_order_and_emits_first_result(self, qapp):
        from translation_assistant.ui import main_widget as mw

        calls = []

        def fake_publish(endpoint, payload):
            calls.append(payload["mode"])
            return {"status": "ok", "mode": payload["mode"], "page_url": "u", "created": payload["mode"] == "replace"}

        with patch.object(mw, "_IllustrationsPublishWorker") as _:
            pass  # ensure the symbol exists; real check below

        worker = mw._IllustrationsPublishWorker(
            "https://site.com",
            [{"mode": "replace"}, {"mode": "append"}, {"mode": "append"}],
        )
        got = {}
        worker.succeeded.connect(lambda r: got.update(r))
        with patch("translation_assistant.wp_publisher.publish_illustrations", fake_publish):
            worker.run()  # run synchronously in-thread for the test

        assert calls == ["replace", "append", "append"]
        assert got["mode"] == "replace"  # first batch's result

    def test_stops_and_reports_on_batch_failure(self, qapp):
        from translation_assistant.ui import main_widget as mw
        from translation_assistant.wp_publisher import WPPublishError

        calls = []

        def fake_publish(endpoint, payload):
            calls.append(payload["mode"])
            if payload["mode"] == "append":
                raise WPPublishError("boom", status_code=500)
            return {"status": "ok"}

        worker = mw._IllustrationsPublishWorker(
            "https://site.com", [{"mode": "replace"}, {"mode": "append"}]
        )
        errs = []
        worker.error.connect(errs.append)
        with patch("translation_assistant.wp_publisher.publish_illustrations", fake_publish):
            worker.run()

        assert calls == ["replace", "append"]
        assert errs and errs[0] == "batch 2/2: boom"
```

- [ ] **Step 2: Run to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_main_window.py -k IllustrationsWorker -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_IllustrationsPublishWorker'`.

- [ ] **Step 3: Implement**

In `translation_assistant/ui/main_widget.py`, immediately after the `_PublishWorker` class (after line 45):

```python
class _IllustrationsPublishWorker(QThread):
    succeeded = Signal(dict)
    error = Signal(str)

    def __init__(self, endpoint_url: str, payloads: list[dict], parent=None) -> None:
        super().__init__(parent)
        self._endpoint_url = endpoint_url
        self._payloads = payloads

    def run(self) -> None:
        from translation_assistant.wp_publisher import publish_illustrations, WPPublishError
        first = None
        for i, payload in enumerate(self._payloads):
            try:
                result = publish_illustrations(self._endpoint_url, payload)
            except WPPublishError as exc:
                self.error.emit(f"batch {i + 1}/{len(self._payloads)}: {exc.message}")
                return
            except Exception as exc:
                self.error.emit(f"batch {i + 1}/{len(self._payloads)}: {exc}")
                return
            if first is None:
                first = result
        self.succeeded.emit(first or {})
```

- [ ] **Step 4: Run to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_main_window.py -k IllustrationsWorker -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "feat(ui): _IllustrationsPublishWorker sends gallery batches in order"
```

---

## Task 5: Menu action + `_on_publish_volume_illustrations` handler

**Files:**
- Modify: `translation_assistant/ui/main_widget.py` — `_build_actions` (near line 205), the enable site (line ~622, inside the method that ends with `self.action_export_md_ruby_doc.setEnabled(True)`), the disable site (line ~1390, after `self.action_publish_wp.setEnabled(False)` in the db-import handler), and new methods `_ensure_wp_ready`, `_on_publish_volume_illustrations`, `_on_publish_illus_done`, `_on_publish_illus_error`.
- Modify: `translation_assistant/ui/combined_window.py` — after line 117 (`file_menu.addAction(ta.action_publish_wp)`).
- Test: `tests/test_main_window.py` (append a `TestPublishVolumeIllustrations` class).

**Interfaces:**
- Consumes:
  - `wp_publisher.build_illustrations_payloads` (Task 2), `_IllustrationsPublishWorker` (Task 4).
  - `imageopt.shrink_image` (Task 1).
  - `self._db.get_document(doc_id) -> dict` with keys incl. `series_title`, `volume_title`.
  - `self._db.get_document_ids_by_volume(series_title: str, volume_title: str) -> list[int]` (series_order-ordered).
  - `self._db.get_document_images(doc_id: int) -> list[dict]` rows with keys `id, anchor_position, is_cover (0/1), src_path, data (bytes), exclude_export (0/1)`.
  - `self._db.get_series_wp_meta(series_title: str) -> {"series_slug", "series_title_short", "syosetu_url"}`.
  - `self._settings.wp_endpoint_url`, `self._settings.wp_api_key`.
  - `self._save_current_translation()`, `self._doc_id`.
- Produces:
  - `self.action_publish_volume_illus: QAction`.
  - `self._ensure_wp_ready(series_title: str) -> tuple[str, str, dict] | None` — returns `(endpoint_url, api_key, series_meta)` or `None` if the user cancels a prompt or leaves required fields blank. May open `WPSettingsDialog` / `SeriesManagerDialog`.
  - `self._on_publish_volume_illustrations()`, `self._on_publish_illus_done(result: dict)`, `self._on_publish_illus_error(message: str)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main_window.py`:

```python
class TestPublishVolumeIllustrations:
    def _widget_with_volume(self, tmp_path):
        w, settings = _make_widget(tmp_path)
        settings.wp_endpoint_url = "https://site.com"
        settings.wp_api_key = "K"
        db = w._db
        db.set_series_wp_meta("S", "s-slug", "S")
        d0 = db.create_document("c0", series_title="S", series_order=0, volume_title="Vol 1")
        d1 = db.create_document("c1", series_title="S", series_order=1, volume_title="Vol 1")
        d2 = db.create_document("c2", series_title="S", series_order=2, volume_title="Vol 2")
        db.add_document_image(d1, 0, True, "cover.png", b"C" * 10)     # volume cover
        db.add_document_image(d1, 1, False, "plate1.png", b"P" * 10)   # inline
        db.add_document_image(d2, 0, False, "other.png", b"O" * 10)    # different volume
        return w, d1

    def test_gathers_volume_images_and_starts_worker(self, qapp, tmp_path, monkeypatch):
        from translation_assistant.ui import main_widget as mw

        w, d1 = self._widget_with_volume(tmp_path)
        w._doc_id = d1

        started = {}

        class FakeWorker:
            def __init__(self, endpoint, payloads, parent=None):
                started["endpoint"] = endpoint
                started["payloads"] = payloads
                self.succeeded = _Sig()
                self.error = _Sig()
            def start(self):
                started["started"] = True

        monkeypatch.setattr(mw, "_IllustrationsPublishWorker", FakeWorker)
        monkeypatch.setattr(mw.QMessageBox, "question",
                            lambda *a, **k: mw.QMessageBox.StandardButton.Yes)
        monkeypatch.setattr("translation_assistant.imageopt.shrink_image", lambda b, **k: b)

        w._on_publish_volume_illustrations()

        assert started.get("started") is True
        assert started["endpoint"] == "https://site.com"
        p0 = started["payloads"][0]
        assert p0["mode"] == "replace"
        assert p0["volume_title"] == "Vol 1"
        assert p0["cover"]["filename"] == "cover.png"
        assert [i["filename"] for i in p0["images"]] == ["plate1.png"]  # only this volume, non-cover

    def test_no_images_shows_info_and_no_worker(self, qapp, tmp_path, monkeypatch):
        from translation_assistant.ui import main_widget as mw

        w, settings = _make_widget(tmp_path)
        settings.wp_endpoint_url = "https://site.com"
        settings.wp_api_key = "K"
        w._db.set_series_wp_meta("S", "s-slug", "S")
        d = w._db.create_document("c1", series_title="S", series_order=1, volume_title="Vol 1")
        w._doc_id = d

        infos = []
        monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: infos.append(a))
        made = []
        monkeypatch.setattr(mw, "_IllustrationsPublishWorker",
                            lambda *a, **k: made.append(a))

        w._on_publish_volume_illustrations()
        assert infos and not made
```

Add this tiny helper near the top of `tests/test_main_window.py` (after the imports) if it is not already present:

```python
class _Sig:
    """Minimal stand-in for a Qt signal in worker fakes."""
    def __init__(self): self._cbs = []
    def connect(self, cb): self._cbs.append(cb)
    def emit(self, *a):
        for cb in self._cbs: cb(*a)
```

- [ ] **Step 2: Run to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_main_window.py -k PublishVolumeIllustrations -v`
Expected: FAIL — `AttributeError: 'TranslationAssistantWidget' object has no attribute '_on_publish_volume_illustrations'`.

- [ ] **Step 3: Add the action in `_build_actions`**

In `translation_assistant/ui/main_widget.py`, right after the `self.action_publish_wp` block (line 207):

```python
        self.action_publish_volume_illus = QAction("Publish Volume Illustrations to WordPress…", self)
        self.action_publish_volume_illus.triggered.connect(self._on_publish_volume_illustrations)
        self.action_publish_volume_illus.setEnabled(False)
```

- [ ] **Step 4: Wire enable/disable**

At the enable site (line ~622, alongside `self.action_publish_wp.setEnabled(True)`):

```python
        self.action_publish_volume_illus.setEnabled(True)
```

At the disable site (line ~1390, alongside `self.action_publish_wp.setEnabled(False)`):

```python
        self.action_publish_volume_illus.setEnabled(False)
```

- [ ] **Step 5: Implement the helper and handlers**

Add these methods to `TranslationAssistantWidget` (place them just before `_on_publish_wp`):

```python
    def _ensure_wp_ready(self, series_title: str):
        """(endpoint_url, api_key, series_meta) once WP settings + series slug
        are known, prompting for whatever is missing; None if the user backs out."""
        from translation_assistant.ui.dlg_wp_settings import WPSettingsDialog

        endpoint_url = self._settings.wp_endpoint_url
        api_key = self._settings.wp_api_key
        if not endpoint_url or not api_key:
            if not WPSettingsDialog(self._settings, parent=self).exec():
                return None
            endpoint_url = self._settings.wp_endpoint_url
            api_key = self._settings.wp_api_key
            if not endpoint_url or not api_key:
                return None

        series_meta = self._db.get_series_wp_meta(series_title)
        if not series_meta["series_slug"] or not series_meta["series_title_short"]:
            from translation_assistant.ui.dlg_series import SeriesManagerDialog
            QMessageBox.information(
                self, "WP Fields Missing",
                f'Set "Series Slug" and "Short Title" for "{series_title}" in Series Manager.',
            )
            dlg = SeriesManagerDialog(self._db, settings=self._settings, parent=self)
            remember_dialog_geometry(dlg, self._settings, "dlg_series")
            dlg.exec()
            series_meta = self._db.get_series_wp_meta(series_title)
            if not series_meta["series_slug"] or not series_meta["series_title_short"]:
                return None
        return endpoint_url, api_key, series_meta

    def _on_publish_volume_illustrations(self) -> None:
        from translation_assistant.wp_publisher import build_illustrations_payloads
        from translation_assistant.imageopt import shrink_image

        self._save_current_translation()
        if self._doc_id is None:
            return
        doc_meta = self._db.get_document(self._doc_id)
        series_title = doc_meta["series_title"]
        volume_title = doc_meta.get("volume_title", "")

        ready = self._ensure_wp_ready(series_title)
        if ready is None:
            return
        endpoint_url, api_key, series_meta = ready

        inline_images: list[dict] = []
        cover_image: dict | None = None
        for d in self._db.get_document_ids_by_volume(series_title, volume_title):
            for im in self._db.get_document_images(d):
                if im["is_cover"]:
                    if cover_image is None:
                        cover_image = im
                elif not im["exclude_export"]:
                    inline_images.append(im)

        if not inline_images and cover_image is None:
            QMessageBox.information(
                self, "No Illustrations",
                "This volume has no illustrations to publish.",
            )
            return

        vol_label = volume_title or series_title
        n = len(inline_images) + (1 if cover_image else 0)
        if QMessageBox.question(
            self, "Publish Volume Illustrations",
            f"Publish {n} illustration(s) from “{vol_label}” to WordPress?\n\n"
            "An existing illustrations page for this volume will be overwritten.",
        ) != QMessageBox.StandardButton.Yes:
            return

        def _shrunk(im: dict) -> dict:
            out = dict(im)
            s = shrink_image(im["data"])
            if s is not im["data"]:
                out["data"] = s
                out["src_path"] = im["src_path"].rsplit(".", 1)[0] + ".jpg"
            return out

        inline_images = [_shrunk(im) for im in inline_images]
        cover_image = _shrunk(cover_image) if cover_image else None

        try:
            payloads = build_illustrations_payloads(
                doc_meta, series_meta, inline_images, api_key=api_key, cover=cover_image,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Payload Error", str(exc))
            return

        self.action_publish_volume_illus.setEnabled(False)
        self._illus_worker = _IllustrationsPublishWorker(endpoint_url, payloads, parent=self)
        self._illus_worker.succeeded.connect(self._on_publish_illus_done)
        self._illus_worker.error.connect(self._on_publish_illus_error)
        self._illus_worker.start()

    def _on_publish_illus_done(self, result: dict) -> None:
        self.action_publish_volume_illus.setEnabled(True)
        word = "Created" if result.get("created") else "Updated"
        url = result.get("page_url", "")
        QMessageBox.information(
            self, "Illustrations Published", f"{word} the volume illustrations page.\n\n{url}",
        )

    def _on_publish_illus_error(self, message: str) -> None:
        self.action_publish_volume_illus.setEnabled(True)
        QMessageBox.warning(self, "Publish Failed", message)
```

- [ ] **Step 6: Add the menu entry**

In `translation_assistant/ui/combined_window.py`, after line 117:

```python
        file_menu.addAction(ta.action_publish_volume_illus)
```

- [ ] **Step 7: Run the new tests**

Run: `source .venv/bin/activate && pytest tests/test_main_window.py -k PublishVolumeIllustrations -v`
Expected: PASS (2 tests).

- [ ] **Step 8: Run the UI test files (no regressions)**

Run: `source .venv/bin/activate && pytest tests/test_main_window.py tests/test_combined_window.py -q`
Expected: PASS (all).

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/ui/main_widget.py translation_assistant/ui/combined_window.py tests/test_main_window.py
git commit -m "feat(ui): Publish Volume Illustrations menu command"
```

---

## Task 6: Plugin — `/illustrations` route + request handler

No PHP test harness. Verification is `php -l` (syntax) plus a curl call against a local WordPress if one is available; otherwise inspect the response shape by reading the code back.

**Files:**
- Modify: `plugins/translation-assistant-publisher/translation-assistant-publisher.php`

**Interfaces:**
- Consumes: `TAP_Auth::validate_key($key): int|false` (existing), `TAP_Publisher::publish_illustrations()` (Task 7 — this task references it; implement the handler now and the method next).
- Produces: `POST /wp-json/ta-publisher/v1/illustrations` → `tap_handle_illustrations(WP_REST_Request $request): WP_REST_Response`. 400 on non-array body, missing `api_key`/`series_title`/`series_slug`/`series_title_short`, empty/absent `images`, or a `mode` that is neither `replace` nor `append`. 401 on bad key. 200 with the publisher result, or 500 `{ "error": <message> }` on `WP_Error`.

- [ ] **Step 1: Register the route**

In `plugins/translation-assistant-publisher/translation-assistant-publisher.php`, inside the `rest_api_init` closure, after the `/status` block (line 28):

```php
    register_rest_route( 'ta-publisher/v1', '/illustrations', [
        'methods'             => 'POST',
        'callback'            => 'tap_handle_illustrations',
        'permission_callback' => '__return_true',
    ] );
```

- [ ] **Step 2: Add the handler function**

After `tap_handle_status()` (line 81):

```php
function tap_handle_illustrations( WP_REST_Request $request ): WP_REST_Response {
    $data = $request->get_json_params();

    if ( ! is_array( $data ) ) {
        return new WP_REST_Response( [ 'error' => 'Request body must be valid JSON' ], 400 );
    }

    // series_link is optional: EPUB-imported series have no source URL.
    $required = [ 'api_key', 'series_title', 'series_slug', 'series_title_short' ];
    foreach ( $required as $field ) {
        if ( ! isset( $data[ $field ] ) || ( empty( $data[ $field ] ) && $data[ $field ] !== 0 ) ) {
            return new WP_REST_Response( [ 'error' => "Missing field: {$field}" ], 400 );
        }
    }
    if ( empty( $data['images'] ) || ! is_array( $data['images'] ) ) {
        return new WP_REST_Response( [ 'error' => 'Missing field: images' ], 400 );
    }
    $mode = $data['mode'] ?? 'replace';
    if ( ! in_array( $mode, [ 'replace', 'append' ], true ) ) {
        return new WP_REST_Response( [ 'error' => "Invalid mode: {$mode}" ], 400 );
    }

    $user_id = TAP_Auth::validate_key( $data['api_key'] );
    if ( ! $user_id ) {
        return new WP_REST_Response( [ 'error' => 'Invalid API key' ], 401 );
    }

    $result = ( new TAP_Publisher() )->publish_illustrations( $data, $user_id );
    if ( is_wp_error( $result ) ) {
        return new WP_REST_Response( [ 'error' => $result->get_error_message() ], 500 );
    }
    return new WP_REST_Response( $result, 200 );
}
```

- [ ] **Step 3: Lint**

Run: `php -l plugins/translation-assistant-publisher/translation-assistant-publisher.php`
Expected: `No syntax errors detected`.

- [ ] **Step 4: Commit**

```bash
cd /home/pun/workspace/wp-dev
git add plugins/translation-assistant-publisher/translation-assistant-publisher.php
git commit -m "feat: add /illustrations REST route and request handler"
```

---

## Task 7: Plugin — `publish_illustrations()` + `build_illustrations_blocks()` + version bump

**Files:**
- Modify: `plugins/translation-assistant-publisher/includes/class-publisher.php`
- Modify: `plugins/translation-assistant-publisher/translation-assistant-publisher.php` (`Version:` header)

**Interfaces:**
- Consumes (all existing in `class-publisher.php`):
  - `find_or_create_index_page( string $series_slug, string $series_title, string $series_link, int $user_id ): int|WP_Error`
  - `attach_image( string $filename, string $mime, string $base64, int $post_id ): int|WP_Error`
  - `image_block( int $attachment_id ): string` (private)
  - `append_toc_entry( int $index_id, string $chapter_title, string $chapter_url, string $volume_title = '' ): void`
  - the attachment-cleanup loop pattern from `update_chapter_page()` (lines 306–314).
- Produces:
  - `TAP_Publisher::publish_illustrations( array $data, int $user_id ): array|WP_Error` — returns `[ 'status' => 'ok', 'page_url' => <permalink>, 'created' => bool, 'updated' => bool ]`.
  - `private function build_illustrations_blocks( array $images, ?array $cover, int $post_id ): string` — `"\n\n"`-joined `wp:image` blocks, cover first when given; skips (and `error_log`s) any image whose `attach_image` fails.

- [ ] **Step 1: Add `build_illustrations_blocks()`**

In `plugins/translation-assistant-publisher/includes/class-publisher.php`, add before `image_block()` (line 540):

```php
    private function build_illustrations_blocks( array $images, ?array $cover, int $post_id ): string {
        $blocks = [];

        if ( $cover !== null ) {
            $cid = $this->attach_image( $cover['filename'], $cover['mime'], $cover['data_base64'], $post_id );
            if ( is_wp_error( $cid ) ) {
                error_log( 'TAP: attach_image (illus cover) failed: ' . $cid->get_error_message() );
            } else {
                $blocks[] = $this->image_block( $cid );
            }
        }

        foreach ( $images as $image ) {
            $aid = $this->attach_image( $image['filename'], $image['mime'], $image['data_base64'], $post_id );
            if ( is_wp_error( $aid ) ) {
                error_log( 'TAP: attach_image (illus) failed for ' . $image['filename'] . ': ' . $aid->get_error_message() );
                continue;
            }
            $blocks[] = $this->image_block( $aid );
        }

        return implode( "\n\n", $blocks );
    }
```

- [ ] **Step 2: Add `publish_illustrations()`**

Add after `publish()` (after line 142):

```php
    public function publish_illustrations( array $data, int $user_id ): array|WP_Error {
        $series_slug  = sanitize_title( $data['series_slug'] );
        $series_link  = isset( $data['series_link'] ) && is_string( $data['series_link'] ) ? $data['series_link'] : '';
        $volume_title = isset( $data['volume_title'] ) && is_string( $data['volume_title'] ) ? $data['volume_title'] : '';
        $mode         = ( $data['mode'] ?? 'replace' ) === 'append' ? 'append' : 'replace';
        $cover        = isset( $data['cover'] ) && is_array( $data['cover'] ) ? $data['cover'] : null;

        $index_id = $this->find_or_create_index_page(
            $series_slug, $data['series_title'], $series_link, $user_id
        );
        if ( is_wp_error( $index_id ) ) return $index_id;

        $slug = $volume_title !== ''
              ? "{$series_slug}-illustrations-" . sanitize_title( $volume_title )
              : "{$series_slug}-illustrations";
        $existing = get_page_by_path( "{$series_slug}/{$slug}", OBJECT, 'page' );

        if ( $mode === 'append' ) {
            if ( ! $existing ) {
                return new WP_Error( 'no_gallery', 'append batch received before replace batch' );
            }
            $blocks = $this->build_illustrations_blocks( $data['images'], null, $existing->ID );
            $update = wp_update_post( [
                'ID'           => $existing->ID,
                'post_content' => rtrim( $existing->post_content ) . "\n\n" . $blocks,
            ], true );
            if ( is_wp_error( $update ) ) return $update;
            return [
                'status'   => 'ok',
                'page_url' => get_permalink( $existing->ID ),
                'created'  => false,
                'updated'  => true,
            ];
        }

        // mode === 'replace'
        $title = $volume_title !== ''
               ? "{$volume_title} — Illustrations"
               : $data['series_title_short'] . ' Illustrations';
        $created = false;

        if ( $existing ) {
            $gallery_id  = $existing->ID;
            $attachments = get_posts( [
                'post_type'   => 'attachment',
                'post_parent' => $gallery_id,
                'numberposts' => -1,
                'post_status' => 'any',
            ] );
            foreach ( $attachments as $attachment ) {
                wp_delete_attachment( $attachment->ID, true );
            }
        } else {
            $gallery_id = wp_insert_post( [
                'post_type'      => 'page',
                'post_title'     => $title,
                'post_name'      => $slug,
                'post_parent'    => $index_id,
                'post_status'    => 'publish',
                'post_author'    => $user_id,
                'post_content'   => '',
                'comment_status' => 'closed',
                'menu_order'     => 0,
            ], true );
            if ( is_wp_error( $gallery_id ) ) return $gallery_id;
            $created = true;
        }

        $blocks = $this->build_illustrations_blocks( $data['images'], $cover, $gallery_id );
        $update = wp_update_post( [
            'ID'           => $gallery_id,
            'post_title'   => $title,
            'post_content' => $blocks,
        ], true );
        if ( is_wp_error( $update ) ) {
            if ( $created ) wp_delete_post( $gallery_id, true );
            return $update;
        }

        $this->append_toc_entry( $index_id, 'Illustrations', get_permalink( $gallery_id ), $volume_title );

        return [
            'status'   => 'ok',
            'page_url' => get_permalink( $gallery_id ),
            'created'  => $created,
            'updated'  => ! $created,
        ];
    }
```

Note: the `—` above is an em dash — write the literal `—` character in the PHP source (`"{$volume_title} — Illustrations"`).

- [ ] **Step 3: Bump the plugin version**

In `plugins/translation-assistant-publisher/translation-assistant-publisher.php`, line 5:

```php
 * Version:     1.5.4
```

- [ ] **Step 4: Lint both files**

Run:
```bash
php -l plugins/translation-assistant-publisher/includes/class-publisher.php
php -l plugins/translation-assistant-publisher/translation-assistant-publisher.php
```
Expected: `No syntax errors detected` for both.

- [ ] **Step 5: Integration check (if a local WordPress is reachable)**

If `/home/pun/workspace/wp-dev` is served by a local WP (check with `wp option get siteurl` or the project's usual dev command), activate the updated plugin and run a two-batch smoke test with a valid API key:

```bash
KEY=<valid-api-key>
BASE=<local-wp-base-url>   # e.g. http://localhost:8080
b64() { base64 -w0 "$1"; }

# batch 1: replace (+cover)
curl -sS -X POST "$BASE/wp-json/ta-publisher/v1/illustrations" \
  -H 'Content-Type: application/json' -d @- <<JSON
{ "api_key":"$KEY","series_title":"Smoke","series_slug":"smoke",
  "series_title_short":"SMK","series_link":"","volume_title":"V1","mode":"replace",
  "cover":{"filename":"c.png","mime":"image/png","data_base64":"$(b64 some-cover.png)"},
  "images":[{"filename":"a.png","mime":"image/png","data_base64":"$(b64 a.png)"}] }
JSON

# batch 2: append
curl -sS -X POST "$BASE/wp-json/ta-publisher/v1/illustrations" \
  -H 'Content-Type: application/json' -d @- <<JSON
{ "api_key":"$KEY","series_title":"Smoke","series_slug":"smoke",
  "series_title_short":"SMK","series_link":"","volume_title":"V1","mode":"append",
  "images":[{"filename":"b.png","mime":"image/png","data_base64":"$(b64 b.png)"}] }
JSON
```

Expected: both return HTTP 200 with `"status":"ok"`; the first has `"created":true`, the second `"updated":true`. Visiting `$BASE/smoke/smoke-illustrations-v1/` shows all three images (cover, a, b) in order, and the series index page at `$BASE/smoke/` has an "Illustrations" link under a `V1` heading. Re-running batch 1 leaves exactly one gallery page and one ToC link (no duplicates).

If no local WP is available, note that in the commit message and rely on `php -l` + code review.

- [ ] **Step 6: Commit**

```bash
cd /home/pun/workspace/wp-dev
git add plugins/translation-assistant-publisher/includes/class-publisher.php plugins/translation-assistant-publisher/translation-assistant-publisher.php
git commit -m "feat: publish_illustrations gallery page (replace/append), bump to 1.5.4"
```

---

## Task 8: Full regression pass

- [ ] **Step 1: Run the entire TA test suite**

Run: `source .venv/bin/activate && pytest -q`
Expected: PASS. Baseline before this plan is 918 tests + the in-flight additions; this plan adds ~18 (`test_wp_publisher.py`, `test_main_window.py`). No pre-existing test should change from pass to fail.

- [ ] **Step 2: If anything fails**, fix it in the owning task's files, re-run, and amend that task's commit (or add a follow-up commit referencing the task).

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Payload size / batching (`mode: replace/append`, ~800 KB) | 2 (`build_illustrations_payloads`), 4 (sequential worker), 7 (plugin `mode` branches) |
| A1 new REST route, optional `series_link`, `mode` validation | 6 |
| A2 `publish_illustrations` slug, find-or-create, replace wipes attachments, append concatenates, `no_gallery` guard | 7 |
| A3 `build_illustrations_blocks` cover-first, `attach_image` tolerance, no NAV/SEPARATOR | 7 |
| A4 version 1.5.3 → 1.5.4 | 7 Step 3 |
| B1 `_ILLUSTRATIONS_PATH`, `publish_illustrations`, error-key parse | 3 |
| B1 `build_illustrations_payloads` (plural) | 2 |
| B2 action, `_ensure_wp_ready`, handler, shrink loop, enable/disable | 5 |
| B2 `_IllustrationsPublishWorker` sequential | 4 |
| B3 menu entry | 5 Step 6 |
| B4 tests | 2, 3, 4, 5 (each task's test steps) |
| B5 `imageopt` dependency tracked | 1 |
| Edge: cover-only volume publishes | 5 test `test_gathers...` covers cover; guard in handler blocks only when both empty |
| Edge: `volume_title == ""` slug/title fallback | 7 (`$volume_title !== ''` branches), 2 (`volume_title` omitted) |
| Edge: re-run overwrites, no dup ToC | 7 Step 5 integration check; `append_toc_entry` idempotency is existing behaviour |
| Edge: `shrink_image` returns same object | 5 (`_shrunk` identity check), 1 (imageopt's own tests) |
| Conflicts table (imageopt, error-key, 1.5.3, series_link) | 1, 3, 6, 7 |

Deviation from spec, deliberate: the spec's B2 says "extract `_ensure_wp_ready` **from** `_on_publish_wp`". This plan adds `_ensure_wp_ready` as a **new** helper used only by the new handler and leaves `_on_publish_wp` untouched, because that function carries uncommitted in-flight edits and refactoring it now risks a merge conflict. Net effect on the codebase is ~15 duplicated lines; the spec's intent (one code path for the readiness check *for this feature*) is met.

**Placeholder scan:** none — every code step has literal content; plugin "integration check" is conditional on a local WP but has a concrete fallback (`php -l` + review).

**Type consistency:** `build_illustrations_payloads` (plural, list return) used consistently in Tasks 2, 4, 5. `publish_illustrations(endpoint_url, payload)` signature identical in Tasks 3, 4. `_IllustrationsPublishWorker(endpoint_url, payloads, parent=None)` identical in Tasks 4, 5. Plugin `publish_illustrations(array $data, int $user_id)` identical in Tasks 6, 7. Result dict keys (`status`, `page_url`, `created`, `updated`) identical in Task 7 and consumed in `_on_publish_illus_done` (Task 5).

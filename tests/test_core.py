"""Cache keys, the manifest, retries and the run log."""
from __future__ import annotations

import json
import unicodedata

import pytest

from pipeline.common import cache, retry, runlog


# --- cache keys -----------------------------------------------------------

def test_key_ignores_dictionary_order():
    a = cache.make_key("keyframes", 1, {"prompt": "a lamp", "seed": 7})
    b = cache.make_key("keyframes", 1, {"seed": 7, "prompt": "a lamp"})
    assert a == b


def test_key_is_the_same_for_composed_and_decomposed_unicode():
    composed = unicodedata.normalize("NFC", "café ሰላም")
    decomposed = unicodedata.normalize("NFD", "café ሰላም")
    assert composed != decomposed
    assert cache.make_key("narration", 1, {"text": composed}) == cache.make_key("narration", 1, {"text": decomposed})


def test_key_changes_when_the_prompt_changes():
    a = cache.make_key("keyframes", 1, {"prompt": "a lamp", "seed": 7})
    b = cache.make_key("keyframes", 1, {"prompt": "a lantern", "seed": 7})
    assert a != b


def test_key_changes_with_seed_stage_and_version():
    base = cache.make_key("keyframes", 1, {"prompt": "a lamp", "seed": 7})
    assert base != cache.make_key("keyframes", 1, {"prompt": "a lamp", "seed": 8})
    assert base != cache.make_key("shots", 1, {"prompt": "a lamp", "seed": 7})
    assert base != cache.make_key("keyframes", 2, {"prompt": "a lamp", "seed": 7})


def test_key_changes_when_an_input_file_changes(tmp_path):
    keyframe = tmp_path / "s01.png"
    keyframe.write_bytes(b"first image")
    before = cache.make_key("shots", 1, {"prompt": "push in"}, {"keyframe": keyframe})
    keyframe.write_bytes(b"second image")
    after = cache.make_key("shots", 1, {"prompt": "push in"}, {"keyframe": keyframe})
    assert before != after


# --- manifest ---------------------------------------------------------------

@pytest.fixture
def manifest(tmp_path):
    return cache.Manifest(path=tmp_path / "outputs" / "manifest.json", store=tmp_path / ".cache" / "store")


def test_manifest_missing_fresh_stale(tmp_path, manifest):
    output = tmp_path / "outputs" / "keyframes" / "s01.png"
    assert manifest.status(output, "key-a") == "missing"

    output.parent.mkdir(parents=True)
    output.write_bytes(b"image made from key-a")
    assert manifest.status(output, "key-a") == "stale"  # a file nobody recorded

    manifest.commit(output, "key-a", stage="keyframes", shot="s01")
    assert manifest.status(output, "key-a") == "fresh"
    assert manifest.status(output, "key-b") == "stale"  # the prompt changed

    output.write_bytes(b"someone edited the file by hand")
    assert manifest.status(output, "key-a") == "stale"


def test_manifest_survives_a_reload(tmp_path, manifest):
    output = tmp_path / "outputs" / "narration" / "s01.wav"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"audio")
    manifest.commit(output, "key-a", stage="narration", shot="s01")

    reloaded = cache.Manifest(path=manifest.path, store=manifest.store)
    assert reloaded.status(output, "key-a") == "fresh"
    assert "outputs/narration/s01.wav" in json.loads(manifest.path.read_text())


def test_undoing_an_edit_restores_the_earlier_output(tmp_path, manifest):
    output = tmp_path / "outputs" / "keyframes" / "s01.png"
    output.parent.mkdir(parents=True)

    output.write_bytes(b"version one")
    manifest.commit(output, "key-1", stage="keyframes", shot="s01")
    output.write_bytes(b"version two")
    manifest.commit(output, "key-2", stage="keyframes", shot="s01")

    assert manifest.restore(output, "key-1", stage="keyframes", shot="s01") is True
    assert output.read_bytes() == b"version one"
    assert manifest.status(output, "key-1") == "fresh"
    assert manifest.restore(output, "never-made", stage="keyframes") is False


# --- retries ----------------------------------------------------------------

def test_retryable_errors_are_retried_until_success():
    calls = []

    def flaky(attempt):
        calls.append(attempt)
        if attempt < 3:
            raise retry.Retryable("503")
        return "done"

    assert retry.with_retries(flaky, attempts=4, sleep=lambda _: None) == "done"
    assert calls == [1, 2, 3]


def test_retries_give_up_after_the_last_attempt():
    def always(attempt):
        raise retry.Retryable("timeout")

    with pytest.raises(retry.Retryable):
        retry.with_retries(always, attempts=3, sleep=lambda _: None)


def test_daily_quota_is_never_retried():
    calls = []

    def exhausted(attempt):
        calls.append(attempt)
        raise retry.QuotaExhausted("daily allowance used")

    with pytest.raises(retry.QuotaExhausted):
        retry.with_retries(exhausted, attempts=5, sleep=lambda _: None)
    assert calls == [1]


def test_backoff_grows_and_is_capped():
    assert retry.backoff_delay(1, base=2, cap=60) <= 2
    assert retry.backoff_delay(10, base=2, cap=60) <= 60
    assert retry.backoff_delay(4, base=2, cap=60) >= 8


# --- run log ----------------------------------------------------------------

def test_a_successful_call_is_logged(isolated_runs):
    with runlog.model_call(stage="keyframes", provider="cloudflare", model="flux", shot="s01",
                           params={"size": 1024}, seed=7, prompt="a lamp") as rec:
        rec["output"] = "outputs/keyframes/s01.png"
        rec["cost"] = {"unit": "neurons", "amount": 104}

    (line,) = runlog.read()
    assert line["event"] == "model_call"
    assert line["status"] == "ok"
    assert line["model"] == "flux" and line["seed"] == 7 and line["shot"] == "s01"
    assert line["cost"]["amount"] == 104
    assert line["latency_s"] >= 0


def test_a_failed_call_is_logged_and_still_raises(isolated_runs):
    with pytest.raises(retry.Retryable):
        with runlog.model_call(stage="narration", provider="gemini", model="tts", attempt=2):
            raise retry.Retryable("429 rate limit")

    (line,) = runlog.read()
    assert line["status"] == "error"
    assert line["attempt"] == 2
    assert "429 rate limit" in line["error"]


def test_experiment_id_tags_the_line(isolated_runs, monkeypatch):
    monkeypatch.setenv("EXPERIMENT", "E4")
    with runlog.model_call(stage="keyframes", provider="cloudflare", model="flux"):
        pass
    assert runlog.read()[0]["experiment_id"] == "E4"


def test_stage_summary_counts(isolated_runs, capsys):
    runlog.stage_summary("keyframes", reused=["s01", "s02"], generated=["s03"])
    (line,) = runlog.read()
    assert (line["reused"], line["generated"], line["generated_items"]) == (2, 1, ["s03"])
    assert "reused 2, generated 1" in capsys.readouterr().out

"""Subtitles, crop geometry, cache keys of the picture stages and the orchestrator's options."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pipeline import assemble, film, keyframes, narration, shots, status, subtitles


# --- subtitles ---------------------------------------------------------------

LONG = "When the rains came, the flame leaned but it never went out, and neither did she."


@pytest.mark.parametrize("max_chars", [30, 40])
def test_every_cue_is_at_most_two_short_lines(max_chars):
    for cue in subtitles.split_text(LONG, max_chars):
        assert 1 <= len(cue) <= 2
        assert all(len(line) <= max_chars for line in cue)


def test_no_word_is_lost_or_reordered():
    cues = subtitles.split_text(LONG, 30)
    assert " ".join(" ".join(cue) for cue in cues) == LONG


def test_two_lines_are_balanced():
    first, second = subtitles.balance("She said a light in the window is a", "promise.", 40)
    assert abs(len(first) - len(second)) < 12
    assert f"{first} {second}" == "She said a light in the window is a promise."


def test_cues_share_the_line_duration_and_stay_inside_the_shot():
    cues = subtitles.cues_for_line(start=10.0, spoken=6.0, limit=18.0, text=LONG, max_chars=30)
    assert cues[0].start == 10.0
    assert all(a.end <= b.start + 1e-6 for a, b in zip(cues, cues[1:]))
    assert cues[-1].end <= 18.0
    assert cues[-1].end == pytest.approx(10.0 + 6.0 + subtitles.LINGER_S, abs=0.01)


def test_a_cue_never_runs_past_its_shot():
    cues = subtitles.cues_for_line(start=10.0, spoken=9.0, limit=12.0, text="A short line.", max_chars=40)
    assert cues[-1].end <= 12.0


def test_build_skips_silent_shots_and_follows_the_timeline(board):
    board["shots"][1]["narration"] = {"text": "", "subtitle_en": ""}
    measured = {shot["id"]: 4.0 for shot in board["shots"] if shot["narration"]["text"]}
    timeline = narration.build_timeline(board, measured)
    cues = subtitles.build(board, timeline, 40)
    assert len(cues) == len(board["shots"]) - 1
    starts = [cue.start for cue in cues]
    assert starts == sorted(starts)
    assert cues[0].start == timeline["shots"][0]["narration_start_s"]


def test_srt_and_ass_formats():
    cues = [subtitles.Cue(0.4, 4.65, ("My grandmother lit this lamp", "every evening.")),
            subtitles.Cue(3725.5, 3727.0, ("A {brace} line",))]
    srt = subtitles.to_srt(cues)
    assert "1\n00:00:00,400 --> 00:00:04,650\nMy grandmother lit this lamp\nevery evening." in srt
    assert "01:02:05,500 --> 01:02:07,000" in srt

    ass = subtitles.to_ass(cues, 1080, 1920, "9x16")
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Dialogue: 0,0:00:00.40,0:00:04.65,Default,,0,0,0,,My grandmother lit this lamp\\Nevery evening." in ass
    assert "A (brace) line" in ass  # braces would be read as style overrides


# --- crop geometry -----------------------------------------------------------

def test_a_centred_crop_of_a_square_for_both_formats():
    assert assemble.crop_box(1024, 1024, 1080, 1920) == (576, 1024, 224, 0)
    assert assemble.crop_box(1024, 1024, 1920, 1080) == (1024, 576, 0, 224)


def test_the_focus_point_moves_the_crop_but_never_outside_the_image():
    width, height, x, y = assemble.crop_box(1024, 1024, 1080, 1920, focus_x=0.95)
    assert (width, height, y) == (576, 1024, 0)
    assert x == 1024 - 576  # clamped to the right edge
    assert assemble.crop_box(1024, 1024, 1080, 1920, focus_x=0.0)[2] == 0


def test_crop_sizes_are_even_numbers():
    for source in (704, 960, 1023, 1440):
        width, height, _, _ = assemble.crop_box(source, source, 1080, 1920)
        assert width % 2 == 0 and height % 2 == 0


def test_zoompan_sets_rate_and_size_explicitly():
    text = assemble.zoompan(204, 1080, 1920, 1.0, 1.1)
    assert ":d=204:s=1080x1920:fps=24" in text  # the filter's defaults are 25 fps and 1280x720
    assert "(on/203)" in text
    assert "1.1" in assemble.zoompan(204, 1080, 1920, 1.0, 1.0, pan="left")  # a pan is given room to travel


# --- cache keys of the picture stages ---------------------------------------

@pytest.fixture
def with_files(tmp_path, monkeypatch, board):
    """Point the picture stages at a temporary outputs folder holding a sheet and a keyframe."""
    from pipeline.common import config
    monkeypatch.setattr(config, "OUTPUTS", tmp_path / "outputs")
    (tmp_path / "outputs" / "refs").mkdir(parents=True)
    (tmp_path / "outputs" / "keyframes").mkdir(parents=True)
    (tmp_path / "outputs" / "refs" / "elder.png").write_bytes(b"reference sheet v1")
    (tmp_path / "outputs" / "keyframes" / "s01.png").write_bytes(b"keyframe v1")
    return tmp_path / "outputs"


def test_every_keyframe_prompt_carries_the_same_character_and_style(board):
    description = board["characters"][0]["description"]
    style = board["style"]["style_block"]
    for shot in board["shots"]:
        prompt = keyframes.shot_prompt(board, shot)
        assert description in prompt and style in prompt and "image 0" in prompt


def test_one_keyframe_prompt_changes_one_keyframe_key(board, with_files):
    before = [keyframes.shot_key(board, shot) for shot in board["shots"]]
    board["shots"][3]["keyframe"]["prompt"] = "Her hands trim the wick of the lamp, close on the hands"
    after = [keyframes.shot_key(board, shot) for shot in board["shots"]]
    assert [a != b for a, b in zip(before, after)] == [i == 3 for i in range(len(before))]


def test_the_style_block_changes_every_keyframe_key(board, with_files):
    before = [keyframes.shot_key(board, shot) for shot in board["shots"]]
    board["style"]["style_block"] += ", cooler palette"
    assert all(a != b for a, b in zip(before, [keyframes.shot_key(board, shot) for shot in board["shots"]]))


def test_a_new_reference_sheet_makes_its_keyframes_stale(board, with_files):
    before = keyframes.shot_key(board, board["shots"][0])
    (with_files / "refs" / "elder.png").write_bytes(b"reference sheet v2")
    assert keyframes.shot_key(board, board["shots"][0]) != before


def test_a_new_keyframe_makes_its_clip_stale_but_a_narration_edit_does_not(board, with_files):
    shot = board["shots"][0]
    before = shots.clip_key(board, shot)
    shot["narration"]["text"] = "ሌላ መስመር።"
    assert shots.clip_key(board, shot) == before
    (with_files / "keyframes" / "s01.png").write_bytes(b"keyframe v2")
    assert shots.clip_key(board, shot) != before


# --- orchestrator options ----------------------------------------------------

def test_force_must_name_a_stage_and_an_output():
    assert film.parse_force("keyframes:s04, narration:s02,keyframes:s05") == {
        "keyframes": {"s04", "s05"}, "narration": {"s02"}}
    assert film.parse_force(None) == {}
    for bad in ("shots", "keyframes:", "everything:s01"):
        with pytest.raises(ValueError):
            film.parse_force(bad)  # there is no way to wipe a whole stage


def test_stage_selection_keeps_pipeline_order():
    assert film.select(None, None) == list(film.STAGES)
    assert film.select("assemble,narration", None) == ["narration", "assemble"]
    assert "shots" not in film.select(None, "shots")
    with pytest.raises(ValueError):
        film.select("keyframe", None)


# --- allowance ledger --------------------------------------------------------

def test_usage_counts_only_calls_since_each_reset():
    now = datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)  # 12:00 EAT, one hour after Gemini's reset
    records = [
        {"ts": "2026-11-26T07:30:00+00:00", "event": "model_call", "provider": "gemini", "model": "tts"},
        {"ts": "2026-11-26T08:30:00+00:00", "event": "model_call", "provider": "gemini", "model": "tts"},
        {"ts": "2026-11-25T23:50:00+00:00", "event": "model_call", "provider": "cloudflare", "status": "ok",
         "cost": {"amount": 104.2}},
        {"ts": "2026-11-26T05:00:00+00:00", "event": "model_call", "provider": "cloudflare", "status": "ok",
         "cost": {"amount": 104.2}},
        {"ts": "2026-11-26T05:01:00+00:00", "event": "model_call", "provider": "cloudflare", "status": "error",
         "cost": {"amount": 104.2}},
        {"ts": "2026-11-26T02:00:00+00:00", "event": "remote_job", "provider": "kaggle", "cost": {"amount": 3600}},
    ]
    used = status.usage(records, now)
    assert used["gemini_calls_since_reset"] == {"tts": 1}
    assert used["cloudflare_images_today"] == 1
    assert used["cloudflare_neurons_today_estimated"] == 104.2
    assert used["kaggle_gpu_session_minutes_this_week"] == 60.0

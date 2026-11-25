"""Timeline arithmetic and the radio-cut text. No provider is called."""
from __future__ import annotations

from pipeline import narration, radio
from pipeline.common import config


def test_a_short_line_keeps_the_planned_length(board):
    timeline = narration.build_timeline(board, {"s01": 3.0})
    first = timeline["shots"][0]
    assert first["duration_s"] == board["shots"][0]["duration_s"]
    assert first["stretched"] is False
    assert first["narration_start_s"] == board["narration"]["lead_in_s"]


def test_a_long_line_stretches_its_shot(board):
    planned = board["shots"][0]["duration_s"]
    spoken = planned + 2.0
    timeline = narration.build_timeline(board, {"s01": spoken})
    first = timeline["shots"][0]
    needed = board["narration"]["lead_in_s"] + spoken + board["narration"]["tail_s"]
    assert first["stretched"] is True
    assert first["duration_s"] >= needed
    assert first["duration_s"] - needed < 1 / config.FPS + 1e-6  # rounded up to one frame at most


def test_shots_are_whole_frames_and_follow_each_other(board):
    measured = {shot["id"]: 6.37 + index * 0.211 for index, shot in enumerate(board["shots"])}
    timeline = narration.build_timeline(board, measured)
    cursor = 0
    for shot in timeline["shots"]:
        assert abs(shot["start_s"] - cursor / config.FPS) < 1e-3
        assert abs(shot["duration_s"] * config.FPS - shot["frames"]) < 1e-2
        cursor += shot["frames"]
    assert abs(timeline["end_card"]["start_s"] - cursor / config.FPS) < 1e-3
    assert timeline["total_frames"] == cursor + timeline["end_card"]["frames"]


def test_a_silent_shot_has_no_narration_start(board):
    timeline = narration.build_timeline(board, {})
    assert all(shot["narration_start_s"] is None for shot in timeline["shots"])
    assert timeline["total_s"] == sum(s["duration_s"] for s in board["shots"]) + board["end_card"]["duration_s"]


def test_the_timeline_is_checked_against_the_window(board):
    fine = narration.build_timeline(board, {})
    assert narration.timeline_problem(fine) is None

    too_long = narration.build_timeline(board, {shot["id"]: 14.0 for shot in board["shots"]})
    problem = narration.timeline_problem(too_long)
    assert problem and "Shorten" in problem and "s01" in problem


def test_the_line_key_changes_only_with_what_matters(board):
    shot = board["shots"][0]
    base = narration.line_key(board, shot)

    board["shots"][1]["narration"]["text"] = "ሌላ መስመር።"
    assert narration.line_key(board, shot) == base  # another shot's line is irrelevant

    shot["keyframe"]["prompt"] = "a completely different picture"
    assert narration.line_key(board, shot) == base  # pictures do not affect speech

    shot["narration"]["text"] = "ሰላም።"
    assert narration.line_key(board, shot) != base

    changed = narration.line_key(board, shot)
    board["narration"]["voice"] = "Puck"
    assert narration.line_key(board, shot) != changed


def test_radio_take_joins_lines_in_order_and_skips_silent_shots(board):
    board["shots"][0]["narration"]["text"] = "አንድ።"
    board["shots"][1]["narration"]["text"] = ""
    board["shots"][2]["narration"]["text"] = "ሦስት።"
    text = radio.take_text(board)
    assert text.startswith("አንድ።\n\nሦስት።")
    assert text.count("\n\n") == len(board["shots"]) - 2

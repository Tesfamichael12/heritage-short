from __future__ import annotations

import json

import pytest

from pipeline import validate


def problems(board: dict) -> list[str]:
    found = validate.schema_problems(board)
    return found or validate.semantic_problems(board)


def test_example_storyboard_is_valid(board):
    assert problems(board) == []


def test_every_shot_needs_a_reason(board):
    del board["shots"][2]["reason"]
    assert any("reason" in p for p in problems(board))


def test_unknown_fields_are_rejected(board):
    board["shots"][0]["keyfrmae"] = {"prompt": "a typo should not pass silently"}
    assert any("keyfrmae" in p for p in problems(board))


def test_shot_count_must_be_eight_to_twelve(board):
    board["shots"] = board["shots"][:7]
    assert any("shots" in p for p in problems(board))


def test_duplicate_shot_ids(board):
    board["shots"][1]["id"] = "s01"
    assert any("more than once" in p for p in problems(board))


def test_unknown_character_reference(board):
    board["shots"][0]["keyframe"]["characters"] = ["nobody"]
    assert any("unknown character" in p for p in problems(board))


def test_planned_length_must_fit_the_window(board):
    for shot in board["shots"]:
        shot["duration_s"] = 12
    assert any("planned length" in p for p in problems(board))


def test_video_frame_count_must_be_4n_plus_1(board):
    board["video"]["num_frames"] = 48
    assert any("4n+1" in p for p in problems(board))


def test_wan_shot_needs_a_motion_prompt(board):
    board["shots"][0]["motion"]["prompt"] = ""
    assert any("motion.prompt" in p for p in problems(board))


def test_end_card_must_say_ai(board):
    board["end_card"]["lines"] = ["A film about the rain", "Thank you for watching"]
    assert any("made with AI" in p for p in problems(board))


def test_narration_and_subtitle_go_together(board):
    board["shots"][0]["narration"]["subtitle_en"] = ""
    assert any("both be set" in p for p in problems(board))


def test_load_reports_a_missing_file(tmp_path):
    with pytest.raises(validate.StoryboardError) as error:
        validate.load(tmp_path / "storyboard.json")
    assert "does not exist yet" in str(error.value)


def test_load_reports_invalid_json(tmp_path):
    path = tmp_path / "storyboard.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(validate.StoryboardError) as error:
        validate.load(path)
    assert "not valid JSON" in str(error.value)


def test_load_returns_the_board(tmp_path, board):
    path = tmp_path / "storyboard.json"
    path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    assert validate.load(path)["film"]["title"] == board["film"]["title"]

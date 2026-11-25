# One command makes the film:  make film
# Every path here is relative, so the repository works from any folder.

PY := uv run python -m pipeline

.PHONY: help setup smoke check validate draft radio film status costs

help:
	@echo "make setup     install dependencies and check that ffmpeg is present"
	@echo "make film      run the whole pipeline from storyboard.json (the one command)"
	@echo "make status    show which outputs are current, stale or missing, and today's call counts"
	@echo "make radio     narration over placeholder music on a black screen"
	@echo "make smoke     call each provider once and log its latency"
	@echo "make check     unit tests, storyboard validation and a scan for committed secrets"
	@echo "make costs     rebuild the tables in COSTS.md from runs.jsonl"
	@echo "make draft     ask Gemini to draft storyboard.draft.json from story/brief.md"
	@echo ""
	@echo "Options:  ONLY=keyframes,narration   run only these stages"
	@echo "          FORCE=keyframes:s04        regenerate one output even if cached"
	@echo "          EXPERIMENT=E4              tag the model calls of this run"

setup:
	@command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }
	@command -v ffmpeg >/dev/null || { echo "ffmpeg is required: https://ffmpeg.org/download.html"; exit 1; }
	uv sync

validate:
	$(PY) validate

smoke:
	$(PY) smoke

check:
	uv run pytest
	$(PY) validate
	$(PY) secrets

draft:
	$(PY) draft

radio:
	$(PY) radio

film:
	$(PY) film $(if $(ONLY),--only $(ONLY)) $(if $(FORCE),--force $(FORCE))

status:
	$(PY) status

costs:
	$(PY) costs

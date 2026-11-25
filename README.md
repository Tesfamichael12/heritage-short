# The Heritage Short

A short film about a family story, narrated in Amharic, and the pipeline that makes it.

The film is 60 to 90 seconds long, in vertical (9:16) and horizontal (16:9), with English subtitles, an original score ducked under the voice, and an end card that says it was made with AI. Nothing was edited by hand. One file, [storyboard.json](storyboard.json), describes the film, and one command turns it into the two finished videos:

```
make film
```

> **Status:** the pipeline is built and tested. The film is in production. This section will name the film and link to it when it is released.

## Run it

You need [uv](https://docs.astral.sh/uv/), FFmpeg 4.4 or newer, and `make`.

```
git clone <this repository>
cd heritage-short
make setup     # installs Python 3.12 and the dependencies into .venv
make film      # runs every stage and writes outputs/final/heritage_9x16.mp4 and heritage_16x9.mp4
```

**No API keys are needed to reproduce the film.** The generated images, audio and clips are committed in `outputs/` together with a manifest of what each was made from. `make film` finds them unchanged, calls no model, and FFmpeg renders both films again from those files in a few minutes.

**To generate from scratch**, or to change the film, copy `.env.example` to `.env` and add your own free keys:

| Key | Where it comes from | Used for |
| --- | --- | --- |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) | storyboard draft, narration |
| `CF_ACCOUNT_ID`, `CF_API_TOKEN` | Cloudflare dashboard, a token from the "Workers AI" template | keyframe images |
| `KAGGLE_USERNAME`, `KAGGLE_API_TOKEN` | Kaggle settings, API section; the account must be phone-verified | video clips and music on a free GPU |

Then run `make smoke`. It calls each provider once and tells you in a minute which keys work.

## What `make film` does

```
storyboard.json
   |  validated against schema/storyboard.schema.json before every stage
   v
narration   Gemini speech         one WAV per shot; the measured lengths set every shot's duration
keyframes   FLUX.2 klein          a character reference sheet, then one still per shot conditioned on it
shots       Wan 2.2 on Kaggle     a short clip for the shots that ask for one
music       ACE-Step 1.5          one score candidate per seed; a person picks one
assemble    FFmpeg                crop to both formats, mix, duck, set loudness, subtitles, end card
qc          FFmpeg                measures the finished films and writes outputs/final/qc.json
```

Each stage skips any output whose inputs have not changed. Run `make film` twice and the second run calls no model. [ARCHITECTURE.md](ARCHITECTURE.md) explains the contract, the caching and the failure handling.

## Change one shot

This is the pipeline's main property, and what the walkthrough video shows.

```
make status                      # everything is current
# edit one keyframe prompt in storyboard.json, for example shot s04
make status                      # s04's keyframe is now STALE; nothing else is
make film SKIP=shots             # one image is generated, one shot is re-rendered
tail -n 6 runs.jsonl             # one new model_call line; "keyframes: reused 9, generated 1"
```

Undoing the edit and running again restores the earlier image from the local store without a new call.

## Commands

| Command | What it does |
| --- | --- |
| `make film` | The whole pipeline, from `storyboard.json` to both films |
| `make status` | What is current, stale or missing, and how much of each free allowance has been used |
| `make radio` | The narration over placeholder music on a black screen, for testing the story before any picture exists |
| `make smoke` | One logged call to each provider |
| `make check` | Unit tests, storyboard validation and a scan for committed secrets |
| `make costs` | Rebuilds the tables in `COSTS.md` from `runs.jsonl` |
| `make draft` | Asks Gemini to draft `storyboard.draft.json` from `story/brief.md`, for a person to edit |
| `make calibrate` | Measures the video model on Kaggle's GPUs before the film's shots are queued |

Options for `make film`: `ONLY=keyframes,assemble` runs only those stages, `SKIP=shots` leaves a stage out, `FORCE=keyframes:s04` regenerates one named output, and `EXPERIMENT=E4` tags the run's model calls in the log.

## What it costs

Nothing. Every model runs on a free tier or as open weights on a free GPU. [COSTS.md](COSTS.md) has the measured latency and GPU time for each stage, the free limits we actually found, and what the same usage would cost at list prices.

| Stage | Model | Runs on | Licence |
| --- | --- | --- | --- |
| Storyboard draft | Gemini 3.8 Flash | Gemini API free tier | Google's API terms |
| Narration | Gemini 3.8 Flash TTS | Gemini API free tier | Google's API terms |
| Keyframes | FLUX.2 klein 4B | Cloudflare Workers AI free allowance | Apache 2.0 |
| Moving shots | Wan 2.2 TI2V-5B | Kaggle, two T4 GPUs | Apache 2.0 |
| Score | ACE-Step 1.5 | Kaggle | MIT |
| Edit | FFmpeg | your machine | LGPL/GPL |

## The repository

```
storyboard.json     the contract: shots, durations, prompts, seeds, narration, music, mix
schema/             JSON Schema for the storyboard
pipeline/           one script per stage, plus shared caching, logging and retry code
pipeline/remote/    the scripts that run on Kaggle
outputs/            every generated image, audio file and clip, with manifest.json
runs.jsonl          one line per model call: model, parameters, seed, latency, cost, status
examples/           a template storyboard for making your own film
tests/              unit tests
```

| Document | What it records |
| --- | --- |
| [DESIGN.md](DESIGN.md) | Who the film is for, what they should feel, the two audience tests and what each changed |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Stages, the contract, caching, logging, failure handling |
| [EXPERIMENTS.md](EXPERIMENTS.md) | Each experiment as hypothesis, change and result |
| [FAILURES.md](FAILURES.md) | What broke, what we tried, what fixed it |
| [COSTS.md](COSTS.md) | Measured latency and GPU minutes, free limits, list-price equivalent |
| [ETHICS.md](ETHICS.md) | Consent, licences, labelling |

## Make your own film

The pipeline knows nothing about this particular story. To make a different film:

1. Write your story in `story/brief.md`, in your own words.
2. `make draft`, then read `storyboard.draft.json`, correct the narration, and save it as `storyboard.json`. Or copy [examples/storyboard.example.json](examples/storyboard.example.json) and write it by hand.
3. `make radio` and play the result to someone from your audience before generating any picture.
4. `make film`.

The narration language is whatever you write the lines in. The speech model detects it.

## How this was made

The story, the audience, the storyboard decisions and the choices between candidates are the author's. The code was written by a coding agent (Claude Code) under the author's direction and review, which the assignment encourages. Every model call the pipeline made is in `runs.jsonl`, including the ones that failed.

The film is labelled as AI-generated on its end card, in the file's metadata and on the platform where it is posted. See [ETHICS.md](ETHICS.md).

## Licence

The code is under the MIT licence ([LICENSE](LICENSE)). The bundled fonts are under the SIL Open Font License ([assets/fonts](assets/fonts/README.md)).

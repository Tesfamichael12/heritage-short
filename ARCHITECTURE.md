# Architecture

This repository is a small film studio in code. One file, `storyboard.json`, describes a 60 to 90 second film. Six stages read that file and each writes one kind of output. `make film` runs them in order and produces the film in two aspect ratios.

```
story/brief.md --(make draft)--> storyboard.draft.json --(a person edits)--> storyboard.json
                                                                                   |
                                               validated before every stage <------+
                                                                                   |
              +----------------------+---------------------+-----------------------+
              v                      v                                             v
        1 narration            2 keyframes                                     4 music
     Gemini speech          FLUX.2 klein on Cloudflare                     ACE-Step 1.5 on Kaggle
     one WAV per shot       reference sheet, then one still per shot       one WAV per seed
              |                      |                                             |
              |                      v                                             |
              |                 3 shots                                            |
              |              Wan 2.2 on Kaggle                                     |
              |              one clip per shot (optional)                          |
              v                      v                                             v
        timeline.json  ------->  5 assemble (FFmpeg, no model)  <------------------+
                                     |
                                     v
                 heritage_9x16.mp4, heritage_16x9.mp4, heritage.srt
                                     |
                                     v
                                6 qc  ->  outputs/final/qc.json
```

## 1. The contract

`storyboard.json` is the only thing a person edits to change the film. Every prompt, seed, model name and parameter lives in it, not in code, so any output can be reproduced and explained from the file alone.

| Block | Holds |
| --- | --- |
| `film` | title, logline, language, audience, intent, target length |
| `style` | one style block and one "avoid" block, appended to every image prompt |
| `characters[]` | id, a fixed description, the reference-sheet prompt, a seed |
| `narration` | speech model, fallback model, voice, style instruction, padding before and after each line |
| `keyframes` | image model, square size, attempts per image |
| `video` | video model, size, frame count, steps, guidance, precision, shots per Kaggle job, time budget |
| `music` | caption, tempo, key, length, seeds, the chosen candidate and why, cue notes |
| `mix` | voice and music levels, ducking settings, loudness target, true-peak ceiling |
| `shots[]` (8 to 12) | `id`, `reason`, shot size, planned length, the spoken line, its English subtitle, the keyframe prompt and seed, the motion mode, prompt, seed and priority, an optional crop focus |
| `end_card` | the lines of the card that says the film was made with AI |

Validation runs before every stage and has two layers ([pipeline/validate.py](pipeline/validate.py)):

1. **JSON Schema** ([schema/storyboard.schema.json](schema/storyboard.schema.json)): shape, types and ranges. Unknown fields are rejected, so a typo such as `keyfrmae` fails loudly instead of being ignored. `reason` is required on every shot.
2. **Checks a schema cannot express:** shot ids are unique, every character a shot refers to exists, a shot whose motion mode is `wan` has a motion prompt and seed, narration and subtitle are both present or both empty, the planned length with the end card is inside 60 to 90 seconds, the video frame count has the form 4n+1, and the end card says "AI".

### Measured values never go back into the contract

The storyboard holds what a person decided. What the pipeline measured goes to derived files:

- `outputs/timeline.json`: the real length of every narration line and the resulting start and length of every shot.
- `outputs/manifest.json`: which inputs each output was made from.
- `outputs/final/qc.json`: the measurements of the finished films.

Keeping the two apart means a run never rewrites the file a person is editing, and the storyboard's git history shows only human decisions.

### The narration sets the cut

A shot lasts as long as its narration needs (the line plus padding) or its planned length, whichever is longer, rounded up to a whole frame. The timeline is rebuilt from the audio files on every run. Because shots can only grow, the storyboard aims at about 72 seconds, and the run warns if the real total leaves the 60 to 90 second window, naming the three longest lines.

## 2. Stages

Each stage is one script in `pipeline/` with a `run(board, manifest, force)` function. A stage reads the storyboard and the files of earlier stages, and writes only its own folder under `outputs/`.

| Stage | Script | Provider and model | Reads | Writes | If it cannot run |
| --- | --- | --- | --- | --- | --- |
| script | `script.py` | Gemini API, `gemini-3.8-flash` | `story/brief.md`, the schema | `storyboard.draft.json` | A person writes the storyboard by hand. Not part of `make film`. |
| narration | `narration.py` | Gemini API, `gemini-3.8-flash-tts` | each shot's line, voice, style | `outputs/narration/sNN.wav`, `timeline.json` | Tries the fallback speech model; on an exhausted daily quota it stops and lists the lines still missing. |
| keyframes | `keyframes.py` | Cloudflare Workers AI, `flux-2-klein-4b` | style, characters, each shot's keyframe prompt | `outputs/refs/<character>.png`, `outputs/keyframes/sNN.png` | Retries with a new seed up to `max_attempts`; then reports the shot as failed. There is no fallback model (see section 7). |
| shots | `shots.py` | Kaggle 2×T4, Wan 2.2 TI2V-5B | keyframes, each shot's motion prompt | `outputs/shots/sNN.mp4` | The shot is rendered as a slow pan and zoom over its keyframe. |
| music | `music.py` | Kaggle, ACE-Step 1.5 | the `music` block | `outputs/music/cand_<seed>.wav` | Assembly uses a generated placeholder drone and the quality check reports it. |
| assemble | `assemble.py` | FFmpeg, no model | everything above, `timeline.json` | both MP4s, `heritage.srt`, subtitle and end-card files | It is deterministic, so it fails loudly. |
| qc | `qc.py` | FFmpeg and ffprobe, no model | the two films | `outputs/final/qc.json` | The run exits non-zero if a limit is missed. |

Supporting commands: `smoke.py` (one logged call per provider), `radio.py` (the audio-only prototype), `calibrate.py` (experiment E7), `status.py`, `costs.py`, `secrets_scan.py`.

### The film is always renderable

Assembly uses whatever exists:

- a shot with a clip plays the clip, then holds on its last frame with a slow push if the shot is longer than the clip;
- a shot with only a keyframe gets a slow pan and zoom over it;
- a shot with neither gets a plain placeholder card, and the quality check fails.

So `make film` produces a playable film at every point in the project. The rough cut is simply an early run of it, and finished clips replace stills one at a time. If the GPU stage fails completely, the film still ships.

## 3. Caching

Every generated file has a **key**: a SHA-256 hash over what decides the file's content ([pipeline/common/cache.py](pipeline/common/cache.py)).

```
key = sha256( canonical_json({
    stage, stage version,
    spec:   model, parameters, prompts, seeds,
    inputs: sha256 of each input file's bytes
}) )
```

Canonical JSON means sorted keys and Unicode NFC normalisation, so the Amharic text hashes to the same key on every machine and operating system. `.gitattributes` marks media as binary and forces LF line endings, so files are byte-identical on every clone.

`outputs/manifest.json` records, for each output, its key and the hash of the file itself. Before doing any work a stage asks for the output's status:

| Status | Meaning | What the stage does |
| --- | --- | --- |
| fresh | the manifest holds this key and the file is unchanged | reuses it |
| stale | a file exists but was made from different inputs, or was edited by hand | regenerates it |
| missing | no file | generates it |

Because input files are hashed by content, changes travel down the chain and no further:

| You change | What regenerates | What does not |
| --- | --- | --- |
| one narration line | that line's WAV, and that shot's video segments | every keyframe, clip and other line |
| one keyframe prompt | that keyframe; its clip becomes stale and the shot falls back to pan and zoom until the GPU stage reruns | every other shot, all narration |
| the style block or a character description | the reference sheet and every keyframe | narration, music |
| one shot's pan or zoom | that shot's two video segments | everything generated by a model |
| the ducking settings | the soundtrack and the final encode | every picture |

Three further rules:

- **Undo is free.** Every generated file is also copied to `.cache/store/<key>` (ignored by git). If an edit is reverted, the earlier output is restored from there without a model call.
- **Forcing is narrow.** `FORCE=keyframes:s04` regenerates one named output. There is deliberately no option that forces a whole stage, because that would discard hours of GPU work.
- **A clean clone needs no keys.** `outputs/` and the manifest are committed. Someone who clones the repository and runs `make film` gets a cache hit for every model call, and FFmpeg renders both films again from those files. If an output is stale and the provider's key is absent, the existing file is used and the run log records `stale_used` instead of crashing.

Assembly has its own content-addressed cache in `.cache/segments/` and `.cache/audio/`: one video segment per shot and format, one soundtrack, and a marker for each final encode. Changing one shot re-renders two segments (one per format) and re-encodes the two films; an unchanged re-run does nothing.

`make status` shows the status of every output and lists what `make film` would generate, before anything is spent.

## 4. Logging

`runs.jsonl` is append-only, one JSON object per line ([pipeline/common/runlog.py](pipeline/common/runlog.py)).

| `event` | Written | Key fields |
| --- | --- | --- |
| `model_call` | once per **attempt** at a provider call, including failures | `stage`, `shot`, `provider`, `model`, `params`, `seed`, `prompt`, `inputs`, `cache_key`, `attempt`, `status`, `error`, `latency_s`, `cost` |
| `remote_job` | once per Kaggle job | `kaggle_ref`, `status`, `wall_s`, `remote_elapsed_s`, `environment` (GPU names, library versions), `cost` |
| `provider_check` | by the smoke test for Kaggle sign-in | `provider`, `status`, `latency_s` |
| `stage_summary` | once per stage run | `reused`, `generated`, `failed`, `generated_items`, `note` |

Every line also carries `ts` (UTC), `run_id`, `git_commit` and `experiment_id` (set with `EXPERIMENT=E4 make ...`).

`cost` is stored in the provider's own unit: tokens for Gemini, neurons for Cloudflare (estimated from the published per-tile price), GPU seconds for Kaggle. Prices are applied later by `make costs`, so a corrected price never requires rewriting the log.

The `stage_summary` lines are the written proof of incremental behaviour: after one keyframe prompt changes, the next run shows `keyframes: reused 9, generated 1 (s04)` and exactly one new `model_call` line.

A call is logged by a context manager that writes in a `finally` block, so a call that raises is still logged, with its error and latency.

## 5. Failure handling

Providers fail in two ways that need opposite responses ([pipeline/common/retry.py](pipeline/common/retry.py)):

| Class | Examples | Response |
| --- | --- | --- |
| `Retryable` | per-minute rate limit, HTTP 5xx, timeout, empty response | exponential backoff with jitter (about 2 s, 4 s, 8 s, capped at 60 s), up to 4 attempts |
| `QuotaExhausted` | Gemini 429 with a per-day quota id; Cloudflare 429 with code 3036 | never retried. The stage stops cleanly, keeps what it has, and prints what is left and when the allowance resets |
| `MissingKey` | a credential absent from `.env` | the stage uses existing files and records `stale_used`, or reports the output as missing |

Other rules:

- **Attempts are bounded.** Three attempts per image, then the shot is reported as failed. One fallback model for speech.
- **Resets are known.** Gemini's daily quota resets at 11:00 East Africa Time, Cloudflare's at 03:00. `make status` counts this project's calls since each reset from `runs.jsonl`.
- **A failed stage does not stop the film** where a fallback exists (see the stages table).
- **Failures are written down** in [FAILURES.md](FAILURES.md) when they happen.

## 6. The remote GPU stage

The video and music models need a GPU, and the only free one is a Kaggle batch session. [pipeline/providers/kaggle.py](pipeline/providers/kaggle.py) turns that into an ordinary function call:

1. **Build.** Copy a stand-alone script from `pipeline/remote/` and put the job description (inputs, tasks, settings) at its top as a JSON string. Write `kernel-metadata.json` asking for a GPU and internet access.
2. **Push.** `kaggle kernels push --accelerator NvidiaTeslaT4` (Kaggle's name for two T4s).
3. **Wait.** Poll `kaggle kernels status` every 45 seconds.
4. **Download.** `kaggle kernels output`, then copy each task's timings into `runs.jsonl`.

A Kaggle job cannot be watched while it runs, and it is not documented whether its outputs survive being killed. The remote scripts are written for that:

- They never raise to the top. Each task's error is caught and recorded with its traceback.
- They stop starting new tasks when the time budget is nearly used, so the job ends by itself.
- They write each clip, and an updated `results.json`, the moment a task finishes.
- Shots are sent in small batches (three by default), most important first, at most two jobs at a time, so one lost job costs a few shots.

**Memory plan for Wan 2.2 on two 16 GB T4s with about 30 GB of RAM** ([pipeline/remote/wan_job.py](pipeline/remote/wan_job.py)):

1. Encode every prompt once on the CPU, then free the text encoder, which alone is about 11 GB. Loading it once per GPU would not fit in RAM.
2. Load one pipeline per GPU without a text encoder, in half precision, with the VAE in full precision.
3. One thread per GPU works through its share of the tasks.

Each finished clip is checked in code for black, non-finite or frozen frames, because the T4 lacks the number format this model prefers and half precision is known to fail silently on some setups. A black clip is reported as a failure, never used.

**ACE-Step** ([pipeline/remote/music_job.py](pipeline/remote/music_job.py)) is run without its language-model planner. The score is instrumental and the storyboard already fixes tempo, key and length, so the planner has nothing to decide; leaving it out removes a download and a way to fail.

## 7. Decisions and their reasons

| Decision | Reason |
| --- | --- |
| Plain Python, a Makefile, no agent or workflow framework | Six stages do not need one. A framework would add failure modes without adding anything a reader could check. |
| Square keyframes with the subject centred | Both aspect ratios are crops of one image, so nothing is generated twice. A per-shot `framing.focus` moves the crop when a subject sits off-centre. |
| Narration drives shot length | The voice is the spine of the film; cutting picture to it is how editors work, and it removes guessing about durations. |
| Only `flux-2-klein-4b` for images, no fallback | On Cloudflare the alternative, `flux-1-schnell`, accepts no seed, no size and no reference image, so it cannot keep a character consistent. A wrong-looking shot is worse than a missing one. |
| The Kaggle CLI drives the GPU stage | It makes a notebook service behave like a function, so one command can run the whole pipeline. |
| Costs logged in provider units | Prices change; units do not. |
| The end card is drawn in Python | It needs one still image. A browser-based renderer would add a toolchain for no gain. |

## 8. Assembly

All of the edit is code, driven by the storyboard and the timeline ([pipeline/assemble.py](pipeline/assemble.py)).

1. **Segments.** One video-only segment per shot and format, with an exact whole number of frames, at 24 frames per second. The source (clip or still) is cropped around the focus point to 9:16 or 16:9 and scaled to 1080×1920 or 1920×1080.
2. **Soundtrack.** Each narration line is brought to the same loudness, then placed at its time on the timeline. The score is trimmed, faded and levelled, then ducked under the voice with a sidechain compressor whose settings come from `mix.duck`. The mix is rendered once, measured, and corrected to the target loudness in a second pass.
3. **Subtitles.** Built from each shot's `subtitle_en` and timed from that line's measured audio, because the speech model returns no word timings. Each cue is at most two lines. Line breaks are decided in code, per format: 30 characters a line for vertical, 40 for horizontal. In the vertical film the text sits above the bottom fifth of the frame, clear of the buttons phone apps draw there. An SRT file is written as well.
4. **End card.** Drawn from `end_card.lines` with the bundled fonts, held for the storyboard's duration.
5. **Final pass.** Segments are joined, fades and subtitles are burned in, and the result is encoded as H.264 video with AAC audio, once per format.

FFmpeg 4.4 has several traps in exactly these steps. Each was reproduced on the build machine before the stage was written, and the fix is in the code:

| Trap | Fix |
| --- | --- |
| The sidechain compressor ends its output when the sidechain input ends, cutting the music off after the last line | The voice track is padded to the full length of the film |
| `amix` divides every input by the number of inputs, which pushed ten voice lines below the ducking threshold | `normalize=0` |
| `loudnorm` outputs 192 kHz audio and reports `-inf` for silence | The output rate is set to 48 kHz and `-inf` is parsed |
| `zoompan` wobbles by about a pixel on a slow zoom and defaults to 25 fps at 1280×720 | The still is enlarged three times first; the rate and size are set explicitly |
| Filters split file paths on `:` | FFmpeg always runs from inside `outputs/` with relative file names |

## 9. Verification

| Check | How |
| --- | --- |
| Unit tests | `make check` runs the tests in `tests/`: schema rejection, cache keys, the manifest, retries, the run log, timeline arithmetic, subtitle splitting, crop geometry, the orchestrator's options |
| No secrets | `make check` scans every file git would commit for key-shaped text and for the values in the local `.env` |
| Providers reachable | `make smoke` |
| Incremental behaviour | run `make film` twice; the second run's `stage_summary` lines show zero generated |
| Film requirements | `outputs/final/qc.json`: length, sizes, frame rate, codecs, loudness, true peak, subtitle count, which shots used video |
| Reproducibility | clone into an empty folder with no `.env` and run `make film` |

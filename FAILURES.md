# Failures

What broke, what we tried, and what fixed it. Entries are written when the failure happens, with the evidence. Times are East Africa Time on 26 November 2026.

## F1. The project folder's name stopped Python from creating an environment

- **When:** 00:50, before any code existed.
- **What broke:** The project folder was named `AI-Content Generation: The Heritage Short`. The colon is the separator character in the Linux `PATH` variable.
- **Evidence:** Python 3.12's own `venv` module contains `if os.pathsep in os.fspath(env_dir): raise ValueError('Refusing to create a venv in ... because it contains the PATH separator :')`. Splitting the folder's `.venv/bin` path on `:` gives two entries, `/…/AI-Content Generation` and ` The Heritage Short/.venv/bin`, and neither exists. FFmpeg's `subtitles` filter splits its arguments on `:` as well.
- **What we tried:** Checked whether the older system Python 3.10 has the same guard. It does not, so it would have created a broken environment silently, which is worse.
- **Fix:** Renamed the folder to `heritage-short`. The parent folder still contains a space (`10x TRP2`); we confirmed `make validate` runs correctly from it because the Makefile and every script use paths relative to the repository root.
- **Lesson:** Check the path before the first install. FFmpeg is always run from inside `outputs/` with relative file names for the same reason.

## F2. The Kaggle command-line tool crashed on start

- **When:** 01:02, straight after `uv sync`.
- **What broke:** `kaggle --version` failed with `ModuleNotFoundError: No module named 'six'`, raised from `kaggle/models/upload_file.py` line 22.
- **Cause:** `kaggle` 2.2.5 imports `six` but does not declare it as a dependency, so a clean install does not bring it in.
- **Fix:** Added `six` to the project's own dependencies in `pyproject.toml`. `kaggle --version` then printed `Kaggle CLI 2.2.5`.
- **Lesson:** A stranger running `make setup` would have hit the same crash at the GPU stage, hours into a run. The smoke test now calls every provider's client once so this class of problem shows up in the first minute.

## F3. Tool facts in the brief were out of date

The brief warned this might happen. We checked each provider's official documentation on 26 November before writing any stage.

| The brief says | What is true today | What we did |
| --- | --- | --- |
| "Gemini 3.8 Flash, Flash-Lite for bulk calls" | There is no 3.8 Flash-Lite. The current light model is `gemini-3.5-flash-lite`. | The storyboard names models explicitly, so swapping one is a one-line change. |
| "FLUX.2 klein or FLUX.1 schnell" on Cloudflare | On Workers AI, `flux-1-schnell` accepts only `prompt` and `steps`: no seed, no size and no reference image. It cannot keep a character consistent. | `flux-2-klein-4b` is the only keyframe model. There is no silent fallback to schnell. |
| A reference sheet conditions every keyframe | Reference images sent to klein must be smaller than 512 by 512 pixels. | The keyframe stage downsizes the sheet to 511 pixels before sending it. |
| Wan 2.2 TI2V-5B on a Kaggle T4, "draft at 480p" | The model card asks for 24 GB of memory and lists one size (1280 by 704). A T4 has 16 GB. We found no published T4 timing anywhere. | A calibration job measures it before any batch is queued. See `EXPERIMENTS.md`. |
| Kaggle's P100 GPU | Retired. The CLI accepts the name but runs on a replacement. | Jobs request `NvidiaTeslaT4` explicitly. |
| Gemini speech "is free on the API" | True, but Google publishes no free-tier request limits; they are only visible per project on the rate-limit dashboard. | We read the real limits from the dashboard and record them in `COSTS.md`. |

## F4. The speech model rejected the request format

- **When:** 26 November, 17:50, the first real speech call (`make smoke`).
- **What broke:** `gemini-3.8-flash-tts` answered `400 INVALID_ARGUMENT: Invalid JSON payload received. Unknown name "speechConfig" at 'generation_config'`. The text call to `gemini-3.5-flash-lite` in the same run worked.
- **Cause:** The 3.8 speech models are served through the newer Interactions API (`client.interactions.create`), not `generate_content`. The voice goes in `generation_config.speech_config` as a list, and the speaking style goes in a `speech_metadata` annotation on the text instead of being written into the text itself.
- **Fix:** Rewrote `synthesize` in `pipeline/providers/gemini.py` against Google's speech-generation guide. The next call returned 3.2 s of 24 kHz mono audio in 5.2 s, with 13 input and 81 output tokens logged.
- **Cost of the failure:** possibly one of the 10 speech requests allowed per day. We do not know whether a rejected request counts, so `make status` counts it.
- **Lesson:** The installed SDK still accepted the old call without complaint, so its type hints were no guide. Only a real request found the problem. That is what the smoke test is for.

## F5. The first Kaggle job ran with no GPU and no internet

- **When:** 26 November, 18:21 to 18:35, the first video calibration job (E7, `heritage-wan-calibration-1126-1821`).
- **What broke:** The job reported `complete`, but its environment line read `"torch": "2.11.0+cpu", "gpu_count": 0`, and `pip install` spent 800 seconds failing with `Failed to resolve 'pypi.org' ([Errno -3] Temporary failure in name resolution)`. No clip was made.
- **Cause:** The job's `kernel-metadata.json` asked for both (`"enable_gpu": true`, `"enable_internet": true`, `"machine_shape": "NvidiaTeslaT4"`, and `--accelerator NvidiaTeslaT4` on the push). Kaggle silently gives a session neither when the account is not phone-verified, so that is the likely cause; we are checking the account.
- **What it cost:** 14 minutes of waiting at the worst possible time, and no GPU quota, since no GPU was attached.
- **Fix:** Both remote jobs now run a preflight before installing anything. It checks that `pypi.org` resolves and that `nvidia-smi` exists, and stops within seconds with a note saying which one is missing.
- **Lesson:** "Complete" from Kaggle means only that the script ended. The remote job and the local report have to say what the session actually had.

## F6. Keyframes copied the reference sheet's layout: two grandmothers in every shot

- **When:** 26 November, about 18:58, the first keyframe run on storyboard v1.
- **What broke:** The reference image was a character sheet with two views of the woman side by side (front and three-quarter), as the plan said. Every keyframe conditioned on it (s02 to s05) reproduced that layout: two copies of the same woman standing next to each other, in a flower field, at a doorway, at a table. The three shots with no character (s01, s07, s08) were fine. The images are kept in `outputs/experiments/F6_two_figure_layout/`.
- **Cause:** FLUX.2 klein treats a reference image as a strong guide to composition, not only to identity. Our prompt said "the same person shown in image 0", which did nothing to stop it copying the pose and the count of figures.
- **Fix:** Two changes, both in the storyboard or the prompt code: the reference is now a single full-length portrait of one woman, and every shot's prompt says "Exactly one person in the picture ... use it only for her face, hair and clothes, not for the layout or pose". The keyframe stage version went from 1 to 2 so every affected image was regenerated. All eight came back with one figure, recognisably the same woman.
- **Lesson:** The standard advice is a turnaround sheet, but with an image-conditioned model the reference's composition leaks into every shot. A single-figure portrait suits this model better.

## F7. Cloudflare's safety filter rejected harmless prompts

- **When:** the same run.
- **What broke:** Four requests came back `400 AiError: Your output has been flagged. Please choose another prompt / input image combination`: the reference sheet twice, and shots s02 and s03 once each. The prompts describe an old woman in a white dress and shawl picking flowers.
- **Cause:** Unknown. The filter judges the generated output, not the prompt, and gives no reason.
- **Fix:** None needed: the keyframe stage already retries with a new seed (seed + 1000 per attempt), and every image succeeded within three attempts. Each rejected attempt is in `runs.jsonl` with its error.
- **Cost:** four extra calls, about 400 neurons of the 10,000 a day.

## F8. The finished films missed the true-peak limit by 0.2 dB

- **When:** 26 November, about 19:00, the first full render.
- **What broke:** The quality check failed both films on `true_peak_db`: -0.8 dBTP measured, against a limit of -1.0. Loudness was right (-14.1 LUFS against -14).
- **Cause:** The loudness pass hit -1.0 dBTP on the uncompressed mix. Encoding to AAC then pushed peaks slightly higher, which is a known property of lossy codecs. The earlier test on placeholder tones did not show it because pure tones have few sharp peaks; speech does.
- **Fix:** The loudness pass now aims 1 dB below the limit (`AAC_HEADROOM_DB` in `pipeline/assemble.py`), and the quality check still measures the encoded file, so the limit is checked where it matters.
- **Lesson:** Measure the delivered file, not the intermediate. The quality-check stage caught this; listening would not have.

## F9. A speech request hung for 12 minutes with no reply and no error

- **When:** 26 November, 20:31 to 20:43 EAT, experiment E2.
- **What broke:** One call to `gemini-3.8-flash-lite-tts` (a single 7-second line) neither returned audio nor raised an error. The call before it, the 47-second single take for E1, had returned in 48 seconds.
- **Cause:** Unknown on Google's side. On ours: the Interactions client was created with no timeout, so a stalled connection waited forever, and the retry helper never got the chance to retry.
- **Fix:** The speech client now has a 180-second timeout (`http_options` in `pipeline/providers/gemini.py`). A timeout counts as retryable, so it would have been retried, paced to the per-minute limit.
- **Side effect:** We stopped the process with a kill signal, so the attempt never reached `runs.jsonl`: the logging runs when a call ends, and this one never ended. A log that only writes on completion cannot record a hang. Writing a "started" line before each call would fix that; not done tonight.

## F10. Kaggle never started the GPU jobs

- **When:** 26 November, 18:47 to 20:32 EAT.
- **What broke:** After the account was phone-verified, the video job (`heritage-shots-1126-1847-b1`, 3 shots) and the music job (`heritage-music-1126-1847`) were both accepted and stayed `queued` for 105 minutes. Our local waits timed out (90 minutes for music, about 105 for video). Neither job ever ran.
- **Cause:** Not reported by Kaggle. The CLI returns only `queued`. Likely a shortage of free T4 sessions in the evening, or quota on a newly verified account not yet active.
- **What we did:** Every shot in v1 uses the pan and zoom over its keyframe, which the pipeline was designed to fall back to. For the score, a music job on a Kaggle **CPU** session started at once (`MUSIC_DEVICE=cpu`, job `heritage-music-1126-2009-cpu`).
- **Lesson:** On a free tier, a GPU is not a resource you can schedule. Planning video as an enhancement on top of a film that already works (the "progressive" design in ARCHITECTURE.md) is what let v1 ship without it.

## F11. The music was made, but the download failed, so the stage reported nothing

- **When:** 26 November, 20:51 to 21:06 EAT.
- **What broke:** The CPU music job finished on Kaggle with all three candidates (`results.json`: seeds 7, 21 and 42, about 12.5 minutes each, no errors). Our stage then reported `no usable track (push_failed)` for all three. The download over a 30 to 40 kB/s connection broke partway through the first 17 MB file: `Connection broken: IncompleteRead(1539238 bytes read, 3069352 more expected)`, leaving a `.kaggle-partial` file.
- **Cause, ours:** `kaggle.run` downloads every output file in one call and treats any exception in it as a failed job, so a network error after a successful job was reported as if the job had never run.
- **What we did:** Downloaded `results.json` alone (`--file-pattern`), which proved the job had worked, then each candidate separately, retrying until no partial file was left.
- **Fix still to make in code:** download the results file first and each output separately with retries, and report "job succeeded, download failed" as its own status.

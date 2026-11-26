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

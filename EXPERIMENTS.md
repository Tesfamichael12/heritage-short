# Experiments

Each entry is a hypothesis, one change, and a result. The seed stays fixed unless the seed is the thing being changed. Model calls made for an experiment are tagged in `runs.jsonl` with its id (`EXPERIMENT=E4 make ...`), and their outputs go to `outputs/experiments/` so they never overwrite the film.

**Hypotheses were written on 26 November 2026 at 01:40 East Africa Time, before any of these experiments was run.** A result is filled in only from a real run. An entry that was never run stays marked "not run", with the reason.

| Id | Question | Status |
| --- | --- | --- |
| E1 | Narration as one take, or one call per line? | done (listening test still to do) |
| E2 | Does a style instruction change the voice? | not run (request hung, F9) |
| E3 | Which voice suits the story? | not run (speech quota) |
| E4 | Does the reference image keep the character the same? | done |
| E5 | A fixed style block, or describing the look each time? | done |
| E6 | Keyframe size: 1024 or 1440 pixels? | done |
| E7 | How fast is Wan 2.2 on a T4, and does half precision work? | not run (no GPU granted) |
| E8 | Motion-only video prompts, or re-describing the subject? | not run (no GPU granted) |
| E9 | Three score candidates; short caption or detailed? | not run yet |
| E10 | Ducking: the brief's settings, or tuned? | done |
| E11 | Loudness: one pass or two? | done, did not match expectation |
| E12 | Pan and zoom: straight from the still, or enlarged first? | done |
| E13 | Do the other Ethiopian languages work? (ceiling work) | not run yet |
| E14 | Reference image: two-view sheet or single portrait? (added after F6) | done, the practice failed |

---

## E1. Narration as one take, or one call per line?

- **Suggested practice being tested:** the brief advises generating narration line by line, one file per shot.
- **Hypothesis:** One call per line gives cheaper re-takes and exact per-shot timing, but the voice may drift between calls, because the model has no memory of the previous line. A single take should sound more like one continuous performance.
- **Change:** the same lines, voice and style instruction, generated once as a single take (`make radio`) and once as one call per line (`make film ONLY=narration`).
- **Measure:** total duration of each; a native speaker's judgement of whether the voice is the same person throughout; number of calls used against the daily quota.
- **Author's expectation, written beforehand:** see `local/STORY-WORKSHEET.md`, section 8.
- **Run:** 26 November, 20:30 EAT, storyboard v1, `gemini-3.8-flash-lite-tts`, voice Kore, same style instruction. `python -m pipeline.experiments E1`; 1 call tagged `E1` in `runs.jsonl`, against the 8 per-line `narration` calls at 19:00. Audio: `outputs/experiments/E1_single_take/single_take.wav` and `outputs/narration/s01.wav` to `s08.wav`.
- **Result:** The single take lasted 46.8 s for all eight lines, in one call that took 48.5 s. The eight separate calls added up to 50.6 s of speech, 3.8 s more: each separate line starts and ends with its own breath and silence. Speaking rate varied between separate lines from 5.6 to 7.3 characters a second (standard deviation 0.56), so pace is not held between calls.
- **What it means for the pipeline:** the single take is 8 times cheaper in quota, which on a 10-a-day limit decides it for the radio cut. Per-line files remain necessary for the film, because the cut is timed shot by shot and one line can be re-taken alone.
- **Still to do:** the author listens to both and says whether the voice sounds like one person throughout. That is the half of the question numbers cannot answer.

## E2. Does a style instruction change the voice?

- **Hypothesis:** The brief says a short style instruction (calm, warm, unhurried) improves a voice more than switching voices. We expect a slower pace, measurable as a longer duration for the same line.
- **Change:** one line, one voice, with and without `style_instruction`.
- **Measure:** duration in seconds; whether the model reads the instruction aloud (a known risk when the instruction is in English and the line in Amharic).
- **Result:** not run. The request (20:31 EAT) never returned: no reply and no error after 12 minutes. The speech client had no timeout, so we stopped the process by hand (FAILURES.md F9). Because the process was killed, the attempt is missing from `runs.jsonl`. The lite model had used its 10 requests a day by then (8 for the narration, 1 for E1, and possibly this one), so it could not be repeated tonight.

## E3. Which voice suits the story?

- **Hypothesis:** Among the prebuilt voices, the choice matters less than E2 for pace but more for whether the narrator sounds like a believable family member.
- **Change:** one line with three voices, everything else fixed.
- **Measure:** a native speaker ranks them and says why.
- **Result:** not run. Each speech model allows 10 requests a day on our free tier; the lite model's 10 went to the v1 narration (8), E1 and E2, and the main model's are kept for the real story's narration.

## E4. Does the reference image keep the character the same?

- **Suggested practice being tested:** generate a reference sheet before any keyframe and condition every keyframe on it.
- **Hypothesis:** With the reference image, the character's face, hair and clothes stay recognisably the same across shots. With only the text description, they drift even with the description held constant.
- **Change:** three shots, same prompts and seeds, generated with and without the reference image.
- **Measure:** side-by-side judgement by the author and at least two other people: "is this the same person?" for each pair. Cost in neurons for each.
- **Author's expectation, written beforehand:** see `local/STORY-WORKSHEET.md`, section 8.
- **Run:** 26 November, 20:25 EAT, storyboard v1 (the fictional sample). `python -m pipeline.experiments E4`; 3 calls tagged `E4` in `runs.jsonl`. Images and `comparison.jpg` in `outputs/experiments/E4_reference_image/`.
- **Change as run:** shots s02, s04 and s06, same prompt (which still contains the full written description of the character) and seed; the film's keyframes (with the reference) against three new images without it.
- **Result:** Without the reference she is the same *type* of person but not the same person. Her hair changes from two long braids to a bun (s04), her shawl changes from a thin green, yellow and red border to a wide multicoloured embroidered one (s02, s06), and her face is visibly different in s04 and s06. With the reference, the braids, the shawl border, the cross pendant and the face hold across all three. Cost: about 109 neurons with the reference against 104 without, so consistency costs about 5%.
- **Who judged:** the assistant, looking at `comparison.jpg`. Still to do: the author and two other people answer "is this the same person?" for each pair.
- **Verdict on the practice:** the suggested practice works, and the text description alone is not enough. But see E14: *which* reference image you use matters as much as using one.

## E5. A fixed style block, or describing the look each time?

- **Hypothesis:** The brief says drift mostly comes from re-describing things differently each time. Identical style text on every prompt should give a more uniform look than paraphrases of the same idea.
- **Change:** three shots with the style block word for word, and the same three with a paraphrased style in each prompt.
- **Measure:** visual judgement of palette and medium consistency.
- **Run:** 26 November, 20:27 EAT. `python -m pipeline.experiments E5`; 3 images plus one filter rejection, tagged `E5`. Results in `outputs/experiments/E5_style_block/`.
- **Change as run:** shots s01, s07 and s08 (no character, so only the style varies). Top row: the film's keyframes, made with the style block word for word. Bottom row: the same prompts and seeds, each with a different paraphrase of the same look (the three paraphrases are in `results.json`).
- **Result:** Across the three shots, the spread (standard deviation) of mean brightness was 0.026 with the fixed block and 0.073 with paraphrases, almost three times larger; the spread of hue variety was 0.015 against 0.053. Saturation was similar (0.015 against 0.013). By eye, the paraphrased s08 turned darker and closer to a photograph, and the paraphrased s07 moved the Bible outdoors in front of a mountain view, so a style phrase ("glowing highland sunlight") changed the content, not only the look.
- **Verdict on the practice:** confirmed. Repeating one style block word for word keeps shots alike, and paraphrasing changes more than style.

## E6. Keyframe size: 1024 or 1440 pixels?

- **Hypothesis:** A vertical crop of a 1024 pixel square is 576 pixels wide and must be enlarged 1.9 times to reach 1080; from 1440 it is 810 wide and enlarged 1.3 times. The larger size should look sharper in the pan-and-zoom shots but cost about 2.3 times the neurons, cutting the day's images from about 90 to about 40.
- **Change:** one keyframe at both sizes, same prompt and seed.
- **Measure:** estimated neurons per image; sharpness of the same region after cropping to 1080×1920.
- **Run:** 26 November, 20:28 EAT. `python -m pipeline.experiments E6`; 1 call tagged `E6`. Results in `outputs/experiments/E6_keyframe_size/`.
- **Result:**

| Size | Estimated neurons | Width of the vertical crop | Enlarged to 1080 by | Edge variance at 1080×1920 |
| --- | --- | --- | --- | --- |
| 1024 | 104 | 576 px | 1.88× | 189 |
| 1440 | 234 | 810 px | 1.33× | 659 |

- **Reading it:** 1440 costs 2.25 times the neurons (about 42 images a day instead of 95) and holds about 3.5 times the fine-detail energy after cropping and enlarging. A caveat: the model does not produce the same picture at a different size from the same seed, so part of the difference is a different composition, not only resolution.
- **Decision:** 1024 stays for v1, because the daily allowance had to cover re-takes (F6 and F7 used 13 extra images). For the final film, the few shots that are held longest could be regenerated at 1440; the measured cost makes that affordable for 3 or 4 shots.

## E7. How fast is Wan 2.2 on a T4, and does half precision work?

- **Why it matters:** the model card asks for 24 GB of memory and names one size. A T4 has 16 GB and lacks the number format the model prefers. We found no published T4 timing, so the size of the day's video budget is unknown until this runs.
- **Hypothesis:** Half precision with model offloading fits in 16 GB and produces a real picture at 704×704. Time grows roughly in proportion to pixels × frames × steps. A 49-frame, 20-step clip at 704×704 takes between 5 and 15 minutes.
- **Change:** one input image and prompt, six settings, each differing from the baseline in one thing: frame count (49 or 81), size (512, 704 or 960 square, or 704×1280 vertical), steps (10 or 20). See `MATRIX` in [pipeline/calibrate.py](pipeline/calibrate.py).
- **Measure:** seconds per clip and per step, peak GPU memory, and an automatic check for black, non-finite or frozen frames. `make calibrate`.
- **Decision this feeds:** the `video` block of the storyboard, and how many shots get generated video.
- **Result:** not run, twice. The first job (18:21) ran on a CPU-only session with no internet (FAILURES.md F5). After the account was phone-verified, the video job `heritage-shots-1126-1847-b1` was pushed at 18:47 with three shots and was still **queued** at Kaggle at 20:30, waiting for a free T4. With the deadline at 23:59 we stopped waiting for it: every shot in v1 uses the pan and zoom. The job script, the black-frame check and the calibration matrix are ready and untested on a GPU.

## E8. Motion-only video prompts, or re-describing the subject?

- **Suggested practice being tested:** the brief says that for image-to-video the prompt needs only the motion and the camera, because the image already holds the subject.
- **Hypothesis:** A motion-only prompt keeps the face and clothes closer to the keyframe. Re-describing the subject invites the model to redraw it.
- **Change:** one shot, same keyframe and seed, with a motion-only prompt and with a prompt that also describes the subject.
- **Measure:** difference between the first and last frame in the subject's region; visual judgement of identity drift.
- **Result:** not run: it needs the GPU that E7 never got.

## E9. Three score candidates; short caption or detailed?

- **Suggested practice being tested:** generate a few candidates and choose one; "the caption matters most".
- **Hypothesis:** Three seeds of one caption differ enough that the first is not reliably the best. A detailed caption (style, mood, instruments, texture) gives music that sits under a voice better than a two-word caption.
- **Change:** three seeds with the storyboard's caption; one more with a short caption.
- **Measure:** each candidate played quietly under the narration; the choice and the reason are recorded in `music.chosen` and `music.choice_reason`. Loudness range and spectral balance measured for each.
- **Author's expectation, written beforehand:** see `local/STORY-WORKSHEET.md`, section 8.
- **Result:** not run yet.

## E10. Ducking: the brief's settings, or tuned?

- **Hypothesis:** The brief's starting point (threshold 0.02, ratio 6, attack 300 ms, release 1500 ms) keeps the narration clear. A slow 300 ms attack may let the first syllable of each line be masked.
- **Change:** `mix.duck.attack_ms` from 300 to a shorter value, everything else fixed.
- **Measure:** the level difference between voice and music during speech and during pauses; whether line openings are audible on a phone speaker.
- **Run:** 26 November, 20:22 EAT, on the film's real narration timeline. `python -m pipeline.experiments E10`. No model call. Results and both ducked tracks in `outputs/experiments/E10_ducking/`.
- **Change as run:** attack 300 ms (the brief) against 50 ms; threshold, ratio and release fixed. The music was the placeholder drone, because the generated score was not ready; a drone is steady, which makes the duck easy to measure.
- **Result (music level, dBFS):**

| Attack | First 300 ms of each line | Middle of each line | Pauses between lines |
| --- | --- | --- | --- |
| 300 ms | -34.5 | -39.3 | -27.5 |
| 50 ms | -36.1 | -41.9 | -28.3 |

The narration sits at -19.4 dBFS mid-line. With the brief's settings the music drops about 12 dB under speech and comes back in pauses. The faster attack lowers the music by a further 1.6 dB at line openings, which is the moment the hypothesis worried about, and 2.6 dB mid-line.
- **Verdict:** the brief's settings already work: the music is 15 dB under the voice even at the first syllable. The faster attack helps by a small, measurable amount. We keep 300 ms for now because a fast duck can be heard "pumping" on a real score; this needs listening on the real score before changing.

## E11. Loudness: one pass or two?

- **Hypothesis:** The brief says a two-pass `loudnorm` is more accurate. One pass should miss the −14 LUFS target by more, and may pump because it adjusts gain as it goes.
- **Change:** the same mix normalised with one pass and with two.
- **Measure:** integrated loudness of each result measured with a different meter (`ebur128`), and the mode `loudnorm` reports (linear or dynamic).
- **Run:** 26 November, 20:23 EAT. `python -m pipeline.experiments E11`. No model call. Files in `outputs/experiments/E11_loudness_passes/`.
- **Change as run:** one premix (the narration timeline plus the ducked drone at -6 dB), normalised to -14 LUFS with a true-peak ceiling of -2 dBTP, once with a single `loudnorm` pass and once with the two-pass method the film uses. Both measured afterwards with `ebur128`, a different meter.
- **Result:**

| | Integrated | Error from -14 | True peak | Loudness range |
| --- | --- | --- | --- | --- |
| Premix | -18.0 LUFS | | +0.4 dBTP | 15.1 LU |
| One pass | -16.0 LUFS | -2.0 LU | -1.8 dBTP | 9.0 LU |
| Two pass | -15.7 LUFS | -1.7 LU | -1.8 dBTP | 7.9 LU |

- **What we learned:** two passes were more accurate, but only by 0.3 LU, and *both* missed the target by far more than the brief implies. The reason is in the log: `loudnorm` reported `dynamic` mode, not `linear`. The premix's peaks (+0.4 dBTP) left no room to raise it 4 dB under a -2 dBTP ceiling with a fixed gain, so `loudnorm` fell back to compressing, and on speech with long pauses (a 15 LU range) it undershoots. The real film's mix, which levels each narration line first, reached -14.3 LUFS by the same two-pass path (see `outputs/final/qc.json`), also in `dynamic` mode.
- **Verdict on the practice:** "two-pass is more accurate" holds, but it is not the thing that matters. Levelling the sources before the final pass, and leaving peak headroom, mattered more. This one did not match what we expected. During development on synthetic tones the two-pass path reported `linear` mode and measured −13.9 LUFS against a −14 target; that was a test, not this comparison.

## E12. Pan and zoom: straight from the still, or enlarged first?

- **Hypothesis:** FFmpeg's `zoompan` positions its window on whole pixels, so a slow zoom on a still at output size visibly wobbles. Enlarging the still first makes each step smaller than a pixel of the output.
- **Change:** the same 1.00 to 1.10 zoom over 120 frames, on the still as it is and on the still enlarged to 5760 pixels.
- **Measure:** frame-to-frame position of a tracked point.
- **Preliminary result (design review, 26 November, synthetic image, not logged in `runs.jsonl`):** without enlarging, 32 backward steps and about ±1.06 pixels of wobble; enlarged first, about 0.19 pixels.
- **Run on a real keyframe:** 26 November, 20:24 EAT. `python -m pipeline.experiments E12`. No model call. Results in `outputs/experiments/E12_zoompan_wobble/results.json`.
- **Change as run:** keyframe s04, cropped to 9:16, zoom 1.00 to 1.10 over 120 frames, centred; once at output size (prescale 1) and once enlarged three times first (prescale 3, what the film uses).
- **Measure:** the frame-to-frame shift of a patch at the centre of the picture, by phase correlation, in output pixels. In a centred zoom the centre should not move at all.
- **Result:**

| Prescale | Centre jitter (std) | Largest single step | Steps that went backwards |
| --- | --- | --- | --- |
| 1 | 0.30 px | 0.65 px | 31 |
| 3 | 0.08 px | 0.23 px | 0 |

- **Verdict:** confirmed on real material. Enlarging first cuts the jitter by about 4 times and removes every backward step, which is what reads as wobble.
- **Cost of the decision:** about 10 seconds of rendering per shot and format on the build machine.

## E13. Do the other Ethiopian languages work? (ceiling work)

- **Why:** the brief could not confirm how well the models handle Afaan Oromo, Tigrinya or Somali, and asks us to find out and document exactly where they fail.
- **What we know before running:** Google's supported-language list includes Tigrinya and Somali for the Flash speech model. Afaan Oromo is not listed.
- **Hypothesis:** Tigrinya, which shares the Ge'ez script with Amharic, will be read in the right script but may be pronounced with Amharic sounds. Somali, in Latin script, will be read fluently. Afaan Oromo, unlisted and in Latin script, will be read with the sounds of another language, most likely English or Somali.
- **Change:** the same two narration lines, translated, in each of the three languages; voice and style fixed.
- **Measure:** a speaker of each language listens and notes which words are wrong and how. Duration per line.
- **Result:** not run yet.

## E14. Which reference image: a two-view character sheet or a single portrait?

*Added during production, after failure F6. Not registered beforehand, so there was no written expectation.*

- **Suggested practice being tested:** the brief, and common advice, say to make a character reference *sheet* (several views of the character) before any keyframe.
- **Change:** the reference image only. Version 1 was a sheet of two views side by side; version 2 a single full-length portrait. Shot prompts, seeds, style and model were otherwise the same, except that version 2 also added the sentence "Exactly one person in the picture ... use it only for her face, hair and clothes, not for the layout or pose". So two things changed together, which we note rather than hide.
- **Result:** With the sheet, all four keyframes that used it (s02 to s05) showed **two** women side by side, copying the sheet's layout; 4 of 4 unusable. With the portrait and the added sentence, 4 of 4 showed one woman, recognisably the same across shots (E4). Images: `outputs/experiments/F6_two_figure_layout/` (version 1) and `outputs/keyframes/` (version 2). Calls: the `refs` and `keyframes` lines in `runs.jsonl` from 18:56 to 19:00 EAT.
- **Verdict on the practice:** with FLUX.2 klein the sheet is harmful: the model treats the reference as a composition to copy. A single portrait works. This is the clearest case today of a suggested practice that failed.

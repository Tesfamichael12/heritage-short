# Experiments

Each entry is a hypothesis, one change, and a result. The seed stays fixed unless the seed is the thing being changed. Model calls made for an experiment are tagged in `runs.jsonl` with its id (`EXPERIMENT=E4 make ...`), and their outputs go to `outputs/experiments/` so they never overwrite the film.

**Hypotheses were written on 26 November 2026 at 01:40 East Africa Time, before any of these experiments was run.** A result is filled in only from a real run. An entry that was never run stays marked "not run", with the reason.

| Id | Question | Status |
| --- | --- | --- |
| E1 | Narration as one take, or one call per line? | not run yet |
| E2 | Does a style instruction change the voice? | not run yet |
| E3 | Which voice suits the story? | not run yet |
| E4 | Does the reference image keep the character the same? | not run yet |
| E5 | A fixed style block, or describing the look each time? | not run yet |
| E6 | Keyframe size: 1024 or 1440 pixels? | not run yet |
| E7 | How fast is Wan 2.2 on a T4, and does half precision work? | not run yet |
| E8 | Motion-only video prompts, or re-describing the subject? | not run yet |
| E9 | Three score candidates; short caption or detailed? | not run yet |
| E10 | Ducking: the brief's settings, or tuned? | not run yet |
| E11 | Loudness: one pass or two? | not run yet |
| E12 | Pan and zoom: straight from the still, or enlarged first? | preliminary |
| E13 | Do the other Ethiopian languages work? (ceiling work) | not run yet |

---

## E1. Narration as one take, or one call per line?

- **Suggested practice being tested:** the brief advises generating narration line by line, one file per shot.
- **Hypothesis:** One call per line gives cheaper re-takes and exact per-shot timing, but the voice may drift between calls, because the model has no memory of the previous line. A single take should sound more like one continuous performance.
- **Change:** the same lines, voice and style instruction, generated once as a single take (`make radio`) and once as one call per line (`make film ONLY=narration`).
- **Measure:** total duration of each; a native speaker's judgement of whether the voice is the same person throughout; number of calls used against the daily quota.
- **Author's expectation, written beforehand:** see `local/STORY-WORKSHEET.md`, section 8.
- **Result:** not run yet.

## E2. Does a style instruction change the voice?

- **Hypothesis:** The brief says a short style instruction (calm, warm, unhurried) improves a voice more than switching voices. We expect a slower pace, measurable as a longer duration for the same line.
- **Change:** one line, one voice, with and without `style_instruction`.
- **Measure:** duration in seconds; whether the model reads the instruction aloud (a known risk when the instruction is in English and the line in Amharic).
- **Result:** not run yet.

## E3. Which voice suits the story?

- **Hypothesis:** Among the prebuilt voices, the choice matters less than E2 for pace but more for whether the narrator sounds like a believable family member.
- **Change:** one line with three voices, everything else fixed.
- **Measure:** a native speaker ranks them and says why.
- **Result:** not run yet.

## E4. Does the reference image keep the character the same?

- **Suggested practice being tested:** generate a reference sheet before any keyframe and condition every keyframe on it.
- **Hypothesis:** With the reference image, the character's face, hair and clothes stay recognisably the same across shots. With only the text description, they drift even with the description held constant.
- **Change:** three shots, same prompts and seeds, generated with and without the reference image.
- **Measure:** side-by-side judgement by the author and at least two other people: "is this the same person?" for each pair. Cost in neurons for each.
- **Author's expectation, written beforehand:** see `local/STORY-WORKSHEET.md`, section 8.
- **Result:** not run yet.

## E5. A fixed style block, or describing the look each time?

- **Hypothesis:** The brief says drift mostly comes from re-describing things differently each time. Identical style text on every prompt should give a more uniform look than paraphrases of the same idea.
- **Change:** three shots with the style block word for word, and the same three with a paraphrased style in each prompt.
- **Measure:** visual judgement of palette and medium consistency.
- **Result:** not run yet.

## E6. Keyframe size: 1024 or 1440 pixels?

- **Hypothesis:** A vertical crop of a 1024 pixel square is 576 pixels wide and must be enlarged 1.9 times to reach 1080; from 1440 it is 810 wide and enlarged 1.3 times. The larger size should look sharper in the pan-and-zoom shots but cost about 2.3 times the neurons, cutting the day's images from about 90 to about 40.
- **Change:** one keyframe at both sizes, same prompt and seed.
- **Measure:** estimated neurons per image; sharpness of the same region after cropping to 1080×1920.
- **Result:** not run yet.

## E7. How fast is Wan 2.2 on a T4, and does half precision work?

- **Why it matters:** the model card asks for 24 GB of memory and names one size. A T4 has 16 GB and lacks the number format the model prefers. We found no published T4 timing, so the size of the day's video budget is unknown until this runs.
- **Hypothesis:** Half precision with model offloading fits in 16 GB and produces a real picture at 704×704. Time grows roughly in proportion to pixels × frames × steps. A 49-frame, 20-step clip at 704×704 takes between 5 and 15 minutes.
- **Change:** one input image and prompt, six settings, each differing from the baseline in one thing: frame count (49 or 81), size (512, 704 or 960 square, or 704×1280 vertical), steps (10 or 20). See `MATRIX` in [pipeline/calibrate.py](pipeline/calibrate.py).
- **Measure:** seconds per clip and per step, peak GPU memory, and an automatic check for black, non-finite or frozen frames. `make calibrate`.
- **Decision this feeds:** the `video` block of the storyboard, and how many shots get generated video.
- **Result:** not run yet.

## E8. Motion-only video prompts, or re-describing the subject?

- **Suggested practice being tested:** the brief says that for image-to-video the prompt needs only the motion and the camera, because the image already holds the subject.
- **Hypothesis:** A motion-only prompt keeps the face and clothes closer to the keyframe. Re-describing the subject invites the model to redraw it.
- **Change:** one shot, same keyframe and seed, with a motion-only prompt and with a prompt that also describes the subject.
- **Measure:** difference between the first and last frame in the subject's region; visual judgement of identity drift.
- **Result:** not run yet.

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
- **Result:** not run yet.

## E11. Loudness: one pass or two?

- **Hypothesis:** The brief says a two-pass `loudnorm` is more accurate. One pass should miss the −14 LUFS target by more, and may pump because it adjusts gain as it goes.
- **Change:** the same mix normalised with one pass and with two.
- **Measure:** integrated loudness of each result measured with a different meter (`ebur128`), and the mode `loudnorm` reports (linear or dynamic).
- **Result:** not run yet. During development on synthetic tones the two-pass path reported `linear` mode and measured −13.9 LUFS against a −14 target; that was a test, not this comparison.

## E12. Pan and zoom: straight from the still, or enlarged first?

- **Hypothesis:** FFmpeg's `zoompan` positions its window on whole pixels, so a slow zoom on a still at output size visibly wobbles. Enlarging the still first makes each step smaller than a pixel of the output.
- **Change:** the same 1.00 to 1.10 zoom over 120 frames, on the still as it is and on the still enlarged to 5760 pixels.
- **Measure:** frame-to-frame position of a tracked point.
- **Preliminary result (design review, 26 November, synthetic image, not logged in `runs.jsonl`):** without enlarging, 32 backward steps and about ±1.06 pixels of wobble; enlarged first, about 0.19 pixels.
- **Decision:** the assembly stage enlarges every still three times before `zoompan` (`PRESCALE` in [pipeline/assemble.py](pipeline/assemble.py)). To be confirmed on a real keyframe.
- **Cost of the decision:** about 10 seconds of rendering per shot and format on the build machine.

## E13. Do the other Ethiopian languages work? (ceiling work)

- **Why:** the brief could not confirm how well the models handle Afaan Oromo, Tigrinya or Somali, and asks us to find out and document exactly where they fail.
- **What we know before running:** Google's supported-language list includes Tigrinya and Somali for the Flash speech model. Afaan Oromo is not listed.
- **Hypothesis:** Tigrinya, which shares the Ge'ez script with Amharic, will be read in the right script but may be pronounced with Amharic sounds. Somali, in Latin script, will be read fluently. Afaan Oromo, unlisted and in Latin script, will be read with the sounds of another language, most likely English or Somali.
- **Change:** the same two narration lines, translated, in each of the three languages; voice and style fixed.
- **Measure:** a speaker of each language listens and notes which words are wrong and how. Duration per line.
- **Result:** not run yet.

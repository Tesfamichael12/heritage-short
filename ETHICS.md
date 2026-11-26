# Ethics: consent, licences and labelling

## 1. Consent

**Status on 26 November 2026, 22:15 East Africa Time:** version 2, *The Comet of Dessie*, is the author's own childhood memory. The record below was written before any of its images or narration were generated. No model call of any kind has been made yet. The smoke test, which runs first, uses generic content only: a lamp on a windowsill and the sentence "Hello. This is a voice test."

The rule this project follows: the consent record below is filled in and committed before the first keyframe, clip or narration line of the film is generated. The run log's timestamps and the commit history show the order.

### Version 1 is fiction

The first `storyboard.json` (committed 26 November, about 18:55 East Africa Time) is a **sample story invented by the AI assistant** at the author's request, to prove the pipeline end to end before the real family story is ready. It depicts and names no real person: the grandmother is fictional and is called only "Emama" (grandmother). No consent was needed for it, and its end card says it is a sample written with AI. The consent record below applies to the real family story that replaces it.

### How real people are handled

- **No real face.** The character in the film is an illustrated figure described in words in `storyboard.json`. No photograph of any person is used as an input to any model.
- **No cloned voice.** The narrator is one of Gemini's stock prebuilt voices, named in `storyboard.json`. No recording of any person's voice is used.
- **A real person's story is still theirs.** Telling it publicly needs their agreement, or their close family's if they have died, and the words in the narration are ones they have agreed to.

### Consent record

To be completed by the author before generation starts.

| Item | Record |
| --- | --- |
| Whose story the film tells | The author's own: a memory of playing street football in Dessie at the age of seven, and of his grandmother's explanation of the town's name |
| Relationship to the author | It is about the author himself; his grandmother and three childhood friends (Seid, Dawit, Hayat) appear in it |
| Who gave consent | The author, for his own story, by writing it and asking for it to be filmed (26 November 2026) |
| What is shown of the other people | Illustrated figures drawn from words only; no photograph, recording or likeness of any real person was used. The grandmother has no name in the film. The friends appear by first name only, in the narration of one line (Hayat) and the subtitles of another (Dawit) |
| Consent from the grandmother and the three friends | **Not recorded.** The author should confirm with them (or with family for the grandmother) or replace the friends' first names before the film is published. Changing a name is one edit to `storyboard.json` and regenerates only that shot's line |
| Names or details left out | Surnames, the exact neighbourhood (sefer), and any detail that would identify the family's home |
| Shown the near-final film before release | See DESIGN.md, test 2 |

## 2. Private data and where it goes

| Sent to | What is sent | The provider's terms |
| --- | --- | --- |
| Gemini API (free tier) | The story brief, narration lines, storyboard prompts | Google's pricing page states that free-tier content is "used to improve our products". |
| Cloudflare Workers AI | Image prompts and the reference sheet image | Cloudflare's data-usage page says customers own their outputs and that it does not train on customer content. |
| Kaggle | Keyframe images, motion prompts, the music caption, inside a private notebook | Stored in the author's Kaggle account. |

Because of the first row, private details stay out of every prompt: no full names, no addresses, no identifying details beyond what the film itself says. The story brief is written with that in mind.

## 3. Licences

Checked on 26 November 2026.

| Component | Used for | Licence | What it means for this film |
| --- | --- | --- | --- |
| FLUX.2 klein 4B (Black Forest Labs), via Cloudflare Workers AI | Reference sheet and keyframes | Apache 2.0 | Outputs may be used freely, including commercially. The 9B variant is non-commercial and is not used. |
| Wan 2.2 TI2V-5B (Alibaba) | Moving shots | Apache 2.0 | Outputs may be used freely. |
| ACE-Step 1.5 | Score | MIT; the authors state it was trained on licensed, royalty-free and synthetic data | Outputs may be used commercially. |
| Gemini 3.8 Flash and Flash TTS (Google) | Storyboard draft, narration | Gemini API terms of service | Output is used under those terms. Generated audio carries Google's SynthID watermark. |
| FFmpeg | Assembly | LGPL/GPL | Used as a tool. It is not distributed with this repository. |
| Noto Sans, Noto Sans Ethiopic (Google) | Subtitles, end card | SIL Open Font License 1.1 | Bundled in `assets/fonts/` with the licence text, as the licence requires. |
| This repository's code | The pipeline | MIT | See `LICENSE`. |

The film and the generated files in `outputs/` are the author's work made with these tools.

## 4. Labelling

The film says it was made with AI in four places, so the statement survives however the file travels:

1. **On screen.** The last three seconds are an end card whose first line is "This film was made with AI", followed by the models used. The text comes from `end_card.lines` in `storyboard.json`, and validation rejects a storyboard whose end card does not say "AI".
2. **In the file.** The MP4's `comment` metadata repeats the end card's text.
3. **On the platform.** The post is published with the platform's AI-content disclosure switched on.
4. **In the post.** The author's own text says how the film was made.

**Watermarks and provenance.** We do nothing to remove any watermark or metadata. Two honest limits:

- The narration carries Google's SynthID audio watermark when it is generated. It is then mixed with music and encoded to AAC. We have not tested whether the watermark is still detectable after that, and we make no claim that it is.
- None of the open models used here attaches C2PA provenance data, so the final file has none. The end card and the metadata comment are the film's provenance statement.

## 5. Style

The look is described by its qualities in `style.style_block` (medium, palette, light, texture). No living artist is named in any prompt, and the storyboard-drafting prompt instructs the model never to name one.

# Design

Who the film is for, what it should leave them with, and what two rounds of testing with that audience changed.

**This document is written by the film's author.** Sections marked *pending* have not happened yet. Nothing here is filled in ahead of the event it describes.

## 1. Audience and intent

**Version 2, the film that is submitted: *The Comet of Dessie*.** The author's own memory, written by the author; the storyboard was committed before any of its images or narration were generated.

- **Who will watch:** Ethiopians in their twenties and thirties, at home and abroad, especially anyone who played street football as a child; on a phone, sound on.
- **The story in one sentence (logline):** A seven-year-old in Dessie builds a football from socks and string, kicks it into the fog in a 4–4 match, and never finds it; his grandmother tells him what comets are for.
- **What they should feel when it ends:** Leave them smiling at their own childhood and proud to say where they are from.
- **The need, as a "how might we" sentence:** How might we make a viewer feel, in about a minute, the joy of a childhood game played with almost nothing, and the pride of a town's name?
- **Why this story:** it is true, it is the author's, and its central image, a comet, connects a town's legend to a child's homemade ball, so the ending lands without explanation.

**Version 1, the fictional sample (superseded):**

**Version 1 (the fictional sample, "The Meskel Flowers").** Written by the AI assistant at the author's request and committed in `1b98b4e` at about 18:55 East Africa Time, before any picture or narration line was generated (the first `keyframes` line in `runs.jsonl` is after that commit). The author's real story replaces this section in version 2.

- **Who will watch:** Ethiopians aged about 20 to 40 who live away from their home town and their parents: students and young workers in Addis Ababa or abroad.
- **Where they will watch:** on a phone, in a social feed, vertical, mostly with sound on but often in a noisy place, so every line is also subtitled.
- **The story in one sentence (logline):** Every September a grandmother presses one Meskel flower for the son who left for the city; years later her family finds thirty of them.
- **What they should feel or understand when it ends:** that a parent's love is often quiet and only becomes visible later, and the urge to call someone at home.
- **The need, as a "how might we" sentence:** How might we make the people who left home feel the patience of the people who stayed, in about a minute, without a single line of dialogue?
- **Why this story, and why now:** Meskel falls in late September, and the yellow adey abeba is the flower every Ethiopian connects with it, so the image carries meaning before the narration explains anything. For the sample it also tests the hard parts of the pipeline: one recurring character across shots, a single object that has to read clearly, and a night scene.

## 2. Ideas considered

For version 1, by the assistant. Design thinking asks for several approaches before choosing one.

| Approach | What it would look like | Why it was or was not chosen |
| --- | --- | --- |
| The son's point of view | He receives a dried flower in a letter in Addis Ababa every year | Needs a second consistent character and city scenes; doubles the consistency problem. Not chosen. |
| The festival itself | A documentary-style film of Meskel and the Demera bonfire | Informative but impersonal; no single feeling for the audience to leave with. Not chosen. |
| One ritual, one object, one reveal | The grandmother's yearly habit, ending on the Bible full of flowers | One character, one place, and an ending the viewer can feel without explanation. **Chosen.** |

## 3. Why each shot exists

Every shot's reason is in `storyboard.json` (`shots[].reason`), and the schema refuses a storyboard that lacks one. The table below is copied from there when the storyboard is locked, with the shot size chosen for each and why.

Version 2, copied from `storyboard.json`:

| Shot | Size | Reason |
| --- | --- | --- |
| s01 | extreme wide | Opens on the legend of the town's name, which the last line pays off, and turns 'comet' into the film's central image. |
| s02 | close | Introduces the boy through the thing he makes with his hands; the homemade ball is the hero object. |
| s03 | wide | Shows the place as a playground: the tilted pitch is the visual joke the whole match depends on. |
| s04 | medium | The comic beat: the rules, and the girl who was better than all the boys. |
| s05 | wide | Raises the stakes and changes the light: the fog turns a game into a mystery. |
| s06 | medium | The climax: the kick, the vanishing ball, and the joke that ends the match. |
| s07 | medium close | The meaning of the film, given by the person who told the legend in shot 1. |
| s08 | extreme wide | Returns to the comet over Dessie in the present, so the name and the memory end as one image. |

Version 1 (the sample), for the record:

| Shot | Size | Reason |
| --- | --- | --- |
| s01 | extreme wide | Sets the place and the season before any person appears, so the flowers mean something when she picks them. |
| s02 | wide | Introduces her through a habit, not a face: the yearly walk is the ritual the whole film rests on. |
| s03 | close | The detail that turns a festival custom into a private one; the audience must see the single flower. |
| s04 | medium | Answers the mystery and names the absence the film is about. |
| s05 | insert | Shows where the love is stored, and plants the object the ending pays off. |
| s06 | wide | The public festival and her private prayer in one image; the emotional peak before the time jump. |
| s07 | insert | The payoff: the count makes years of silent love visible at once. |
| s08 | extreme wide | Returns to the hill without her, so the ending lands as memory and a promise. |

## 4. and 5. Audience tests

**What happened, as reported by the author on 26 November 2026 at about 22:10 East Africa Time:** the author showed the film to two groups of viewers and asked the questions below. The author reports that every response was positive and that every question was answered.

**What is missing, and why it matters:** the individual answers were not written down when they were given, and the testers' initials, relationship to the story and exact words were not recorded. They are left blank below rather than reconstructed from memory, because an invented quote is worse than a missing one. The rubric asks for evidence of what testers said, and this section does not provide it; that is a real gap in this submission.

Two things also differ from the plan. Both tests were held on the same evening instead of hours apart, so no storyboard change came out of test 1 before test 2. And the version tested was the sample film (v1) and/or *The Comet of Dessie* (v2); the author should note which one each group saw.

**Test 1: the radio cut or first cut.** Questions: tell me the story back in one sentence; what did you feel at the end; was there a moment you lost interest or wanted more; did any word sound wrong; is anything missing?

| Person (initials) | Relationship to the story | What they said |
| --- | --- | --- |
| *not recorded* | | |

**Test 2: the near-final cut.** Questions: what is this film about; what did you feel at the end; is it the same person in every shot; could you read the subtitles and hear every word over the music; would you send it to someone?

| Person (initials) | Relationship to the story | What they said |
| --- | --- | --- |
| *not recorded* | | |

**What changed because of testing:** nothing in the storyboard, since all responses were positive. The biggest change of the day came from the author, not the testers: replacing the fictional sample with the author's own story (commit `38c2f38`).

**What we would do differently:** write each answer down in the person's own words at the moment it is given, with their initials and the commit they saw, and leave a few hours between the tests so the first can change the storyboard.

## 6. What we would test next

- Whether viewers who do not speak Amharic follow the story from the subtitles alone, and whether the fog shot (s05) reads as fog on a small phone screen.
- Whether the punchline in s06 ("GOAL!" shouted Dawit) lands without seeing Dawit on screen.
- Real motion on s02, s06 and s07 (the GPU job is written), against the same shots as pan and zoom: does motion change what viewers feel, or only how polished it looks?

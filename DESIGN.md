# Design

Who the film is for, what it should leave them with, and what two rounds of testing with that audience changed.

**This document is written by the film's author.** Sections marked *pending* have not happened yet. Nothing here is filled in ahead of the event it describes.

## 1. Audience and intent

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

Version 1, copied from `storyboard.json`:

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

## 4. Test 1: the radio cut

The radio cut is the whole narration over placeholder music on a black screen (`make radio`). It is the cheapest thing that can be reacted to, and it is tested before any picture exists so that the story can still change for free.

*Pending.*

- **Date and time:**
- **Storyboard commit that was tested:**
- **How it was shared:**

| Person (initials) | Relationship to the story | How they listened |
| --- | --- | --- |
|  |  |  |
|  |  |  |
|  |  |  |

**Questions asked**

1. Tell me the story back in one sentence.
2. What did you feel at the end?
3. Was there a moment where you lost interest, or wanted more?
4. Did any word sound wrong or unnatural?
5. Is anything missing that belongs in this story?

**What they said** (their words, as close as possible)

| Person | What they said |
| --- | --- |
|  |  |

**What we learned**

**What changed because of it**

| Change to the storyboard | Because | Commit |
| --- | --- | --- |
|  |  |  |

## 5. Test 2: the near-final cut

*Pending.*

- **Date and time:**
- **Storyboard commit that was tested:**
- **Which version was shown:** (vertical or horizontal, on which device)

| Person (initials) | Relationship to the story | In test 1 as well? |
| --- | --- | --- |
|  |  |  |
|  |  |  |
|  |  |  |

**Questions asked**

1. What is this film about?
2. What did you feel at the end?
3. Is it the same person in every shot? Where did you doubt it?
4. Could you read the subtitles comfortably? Could you hear every word over the music?
5. Would you send this to someone? To whom?

**What they said**

| Person | What they said |
| --- | --- |
|  |  |

**What we learned**

**What changed because of it**

| Change | Because | Commit |
| --- | --- | --- |
|  |  |  |

## 6. What we would test next

*Pending.*

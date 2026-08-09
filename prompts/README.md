# 📝 `prompts/` — Master LLM System Prompts

The `prompts/` directory contains the core system prompt templates that define Drona's persona, lesson plan authoring density, whiteboard event formatting, and question classification taxonomy.

---

## 📂 Prompt Templates

| Prompt File | Consuming Service | Target Model | Key Directive |
|---|---|---|---|
| [`planner.md`](file:///Users/raasikhnaveed/Desktop/monk-learning-api/prompts/planner.md) | `planner.py` | `deepseek-v4-pro` | Authors 6–9 segments per subtopic with **6 to 9 board_content items per segment** (~60 total). |
| [`tutor.md`](file:///Users/raasikhnaveed/Desktop/monk-learning-api/prompts/tutor.md) | `tutor.py` | `deepseek-v4-flash` | Drives turn speech, board event emission, anti-repetition rules, and question classifications. |
| [`scoping.md`](file:///Users/raasikhnaveed/Desktop/monk-learning-api/prompts/scoping.md) | `scoping.py` | `deepseek-v4-flash` | Classifies out-of-topic utterances into Tiers 1–5 for crisis handling and redirects. |

---

## 🎯 Question Taxonomy (`tutor.md` Rule 8 & 9)

> [!IMPORTANT]
> **ANY SPEECH ENDING IN `?` GETS AN ASK SHEET BOX.** Only pure transitions without a question mark return `phase_request: "teaching"`.

```mermaid
flowchart TD
    Start[Tutor Generates Spoken Speech] --> CheckQuestion{Does Speech End in '?' or Contain Question?}
    
    CheckQuestion -- NO --> Teaching[phase_request: 'teaching']
    Teaching --> NullType[question_type: null]
    NullType --> EmptyOpts[check_options: []]

    CheckQuestion -- YES --> Awaiting[phase_request: 'awaiting_answer']
    Awaiting --> Classify{Classify Question Intent}
    
    Classify -- Understanding Check-in --> UndType[question_type: 'understanding']
    UndType --> UndOpts["check_options: ['Haan, samajh aaya', 'Thoda dubara samjhao'] (2 chips)"]

    Classify -- Procedural Transition --> ProcType[question_type: 'procedural']
    ProcType --> ProcOpts["check_options: ['Haan, aage badho', 'Ek baar dubara samjhao'] (2 chips)"]

    Classify -- Content Check / Checkpoint --> ContentType[question_type: 'check' or 'checkpoint']
    ContentType --> ContentOpts["check_options: 3 plausible option chips"]
```

### Classification Taxonomy Table

| Kind | Example Spoken Text | `phase_request` | `question_type` | Options Emitted |
|---|---|---|---|---|
| **Understanding Check-in** | *"samajh aaya?"*, *"clear hai?"* | `awaiting_answer` | `understanding` | `["Haan, samajh aaya", "Thoda dubara samjhao"]` (2 chips) |
| **Procedural** | *"aage badhein?"*, *"next topic pe?"* | `awaiting_answer` | `procedural` | `["Haan, aage badho", "Ek baar dubara samjhao"]` (2 chips) |
| **Content Question** | Recall, application, numerical | `awaiting_answer` | `check` / `checkpoint` | 3 plausible option chips |
| **Pure Transition** | *"Chalo aage badhte hain"* | `teaching` | `null` | None |

---

> [!TIP]
> **Thinking Mode Flag**: All prompts MUST be called with `extra_body={"thinking": {"type": "disabled"}}` to prevent DeepSeek Flash from spending token budget in reasoning mode.

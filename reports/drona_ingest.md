# DRONA v1 — HALT-1 COMPLETED REPORT (POST BLOCKING CORRECTIONS A & B)

> [!IMPORTANT]
> **HALT-1 REMEDIATION & RE-CALIBRATION COMPLETE**: All deleted Maths & STEM chunks restored (5,364 chunks), revised structural noise filter applied safely (98 noise chunks deleted, all subjects <2.5% deletion ratio), and Two-Stage Free-Text Gate (Stage 1 Cosine Shortcut >=0.50 + Stage 2 LLM Classifier) verified across all 15 student queries with 100% accuracy.

## 1. CORRECTION A — MATHS RESTORATION & SAFE REVISED JUNK PURGE
- **Chunk Restoration**: Re-ingested all master PDFs to restore 100% of Maths & STEM dense LaTeX chunks.
- **Revised Purge Rule**: Removed alpha-ratio filter entirely. Targeted ONLY pure structural noise (chunks under 60 chars or >25% dot-leader/dash noise `....`, `----`).
- **Total Inspected Chunks**: 5364
- **Deleted Structural Noise Chunks**: **98** (1.83%)
  - **BIOLOGY**: Total=1210 | Deleted=21 (1.74%) — **SAFE <5%**
  - **CHEMISTRY**: Total=901 | Deleted=3 (0.33%) — **SAFE <5%**
  - **MATHEMATICS**: Total=1500 | Deleted=33 (2.20%) — **SAFE <5%**
  - **PHYSICS**: Total=1753 | Deleted=41 (2.34%) — **SAFE <5%**
- **Remaining Clean Vector Chunks**: **5,266** (`vector(1536)` embeddings)

### 5 Samples Per Subject of Deleted Items (Over-Reach Verification)
#### BIOLOGY SAMPLES (5 items)
[1] `b12_ch11_organisms-populations_MASTER.pdf` (Reason: TOC dot leaders / dash noise (29.3% noise)):
```text
Contents
1
Organism and Its Environment: Levels of Organisation, Niche & Major Abiotic
Factors
1
1.1 Concept Intuition . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ....
```

[2] `Drona_Ch10_Biotechnology_Applications_MASTER.pdf` (Reason: TOC dot leaders / dash noise (25.2% noise)):
```text
5.2 Key Terms, Tools & Constructs
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
24
5.3 Key Processes & Mechanisms . . . . . . . . . . . . . . . . . . . . . . . . . . ...
```

[3] `b12_ch03_reproductive-health_master.pdf` (Reason: TOC dot leaders / dash noise (30.1% noise)):
```text
Reproductive Health
Class 12 Biology · Chapter 3 · Master Content
Drona Ed Tech
June 2026
Contents
1
Birth Control & Contraception
1
1.1 Concept Intuition . . . . . . . . . . . . ....
```

[4] `b11_ch10_cell-cycle-cell-division-2.pdf` (Reason: TOC dot leaders / dash noise (29.2% noise)):
```text
Cell Cycle and Cell Division
Class 11 Biology · Chapter 10 · Drona Ed Tech
Exam-ready study material
Contents
Cell Cycle & Mitosis
1
Section 1: Concept Intuition
. . . . . . . . . ...
```

[5] `b11_ch17_locomotion-and-movement.pdf` (Reason: TOC dot leaders / dash noise (26.2% noise)):
```text
Section 3 — Key Mechanisms & Processes: The Contraction–Relaxation Cycle .
17
Section 4 — Worked Examples . . . . . . . . . . . . . . . . . . . . . . . . . . .
19
Section 5 — Pract...
```

#### CHEMISTRY SAMPLES (3 items)
[1] `c11_ch02_atom_chapter-2.pdf` (Reason: TOC dot leaders / dash noise (26.3% noise)):
```text
Contents
Subatomic Particles & Early Atomic Models . . . . . . . . . . . . . . . . . . . . .
1
Section 1: Concept Intuition . . . . . . . . . . . . . . . . . . . . . . . . . . .
2
...
```

[2] `c11_ch09_hydrocarbons_master.pdf` (Reason: Under 60 characters (46 chars)):
```text
ars in NEET/JEE as a stability-ordering MCQ.
1...
```

[3] `c11_ch09_hydrocarbons_master.pdf` (Reason: TOC dot leaders / dash noise (29.4% noise)):
```text
Contents
Classification of Hydrocarbons . . . . . . . . . . . . . . . . . . . . . . . . . . . .
1
Cycloalkanes — the alicyclic bridge . . . . . . . . . . . . . . . . . . . . . . .
...
```

#### MATHEMATICS SAMPLES (5 items)
[1] `Ch12_Limits_and_Derivatives-2.pdf` (Reason: TOC dot leaders / dash noise (27.4% noise)):
```text
. . . . . . .
13
Subtopic 03 — Derivatives and First Principle
15
Section 1 — Concept Intuition
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
15
Section 2 — Key...
```

[2] `m11_ch10_conics_chapter_complete.pdf` (Reason: TOC dot leaders / dash noise (27.8% noise)):
```text
Conic Sections
Drona Ed Tech
Section 5: Practice Exercises . . . . . . . . . . . . . . . . . . . . . . . . . . . .
25
Section 6: Crack the MCQ
. . . . . . . . . . . . . . . . . . ....
```

[3] `Ch08_Sequences_and_Series_Class11-2.pdf` (Reason: TOC dot leaders / dash noise (25.7% noise)):
```text
falls, Pro-Tips & Cheat Sheet . . . . . . . . . . . . . . . . . .
58
2...
```

[4] `ch11_3dgeom_master.pdf` (Reason: TOC dot leaders / dash noise (29.8% noise)):
```text
Intuition
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
16
Section 2 — Key Formulas & Definitions . . . . . . . . . . . . . . . . . . . . . . . . .
17
Section 3 — CBS...
```

[5] `Chapter07_Binomial_Theorem_MASTER.pdf` (Reason: TOC dot leaders / dash noise (25.8% noise)):
```text
. . . . . . . . . .
18
Section 4: Worked Examples . . . . . . . . . . . . . . . . . . . . . . . . . .
18
Section 5: Practice Exercises . . . . . . . . . . . . . . . . . . . . . . ....
```

#### PHYSICS SAMPLES (5 items)
[1] `ch08_electromagnetic_waves_master.pdf` (Reason: TOC dot leaders / dash noise (27.6% noise)):
```text
Chapter Contents
Subtopic 01 — Displacement Current and Maxwell’s Equations
2
Section 1: Concept Intuition . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ....
```

[2] `Chapter_07_Alternating_Current_MASTER.pdf` (Reason: TOC dot leaders / dash noise (27.4% noise)):
```text
Alternating Current
Chapter 7 · Class 12 Physics — Complete Master Reference
CBSE · JEE Main · JEE
Advanced · NEET
Drona · AI Tutoring
Contents
Subtopic 00 — AC Fundamentals: Avera...
```

[3] `Ch08_Mechanical_Properties_of_Solids_MASTER.pdf` (Reason: TOC dot leaders / dash noise (27.4% noise)):
```text
. . . . . . . . .
18
Section 2: Key Formulas & Definitions . . . . . . . . . . . . . . . . . . . . . . . .
19
Section 3: Derivations & Key Procedures
. . . . . . . . . . . . . . . ...
```

[4] `ch06_electromagnetic_induction_master.pdf` (Reason: TOC dot leaders / dash noise (25.7% noise)):
```text
Electromagnetic Induction
Class 12 Physics, Chapter 6 — Complete Master Notes
Drona
CBSE Boards | NEET | JEE Main | JEE Advanced
Contents
Experimental Foundations — The Faraday & H...
```

[5] `Chapter_11_Thermodynamics_Drona_Master.pdf` (Reason: TOC dot leaders / dash noise (29.9% noise)):
```text
14
Section 7: Common Student Pitfalls & Pro-Tips
. . . . . . . . . . . . . . . . . . . . . .
14
Section 8: Cheat Sheet Box . . . . . . . . . . . . . . . . . . . . . . . . . . . . ....
```

## 2. CORRECTION B — TWO-STAGE FREE-TEXT SYLLABUS GATE
- **Stage 1 (Cosine Shortcut)**: Unfiltered top-5 cosine similarity retrieval. If `top1_score >= 0.50` $\rightarrow$ Accept immediately (`grounded: true`). Zero LLM cost.
- **Stage 2 (LLM Classifier Fallback for `top1_score < 0.50`)**: Lightweight classifier call with thinking **OFF**. Passes student query + top-5 candidate chapter names. Evaluates in-syllabus intent regardless of Hinglish, typos, or informal phrasing.
- **Telemetry**: Logs `top1_similarity` on every free-text session in `drona_sessions`.

### Two-Stage Gate Validation Results (All 15 Queries — 100% Accuracy)
| Query Category | Student Query Text | Top-1 Score | Route Taken | Outcome | Matched / Candidate Chapter |
|---|---|---|---|---|---|
| 1. In-syllabus Physics | `combination of cells in series and parallel` | `0.3942` | `stage2_llm_accepted` | **PASSED (Grounded)** | Current Electricity |
| 2. In-syllabus Biology | `photosynthesis light reaction electron transport` | `0.4315` | `stage2_llm_accepted` | **PASSED (Grounded)** | Photosynthesis in Higher Plants |
| 3. In-syllabus Chemistry | `SN1 versus SN2 mechanism` | `0.6808` | `stage1_cosine_shortcut` | **PASSED (Grounded)** | Haloalkanes & Haloarenes |
| 4. Out-of-syllabus Plausible | `how do I manage exam stress` | `0.3223` | `stage2_llm_declined` | **PASSED (Declined)** | Human Health and Disease |
| 5. Out-of-syllabus Clear | `the French Revolution` | `0.1428` | `stage2_llm_declined` | **PASSED (Declined)** | Photosynthesis in Higher Plants |
| 6. In-syllabus Hinglish Math | `mujhe integration samajh nahi aa raha` | `0.2773` | `stage2_llm_accepted` | **PASSED (Grounded)** | Integrals |
| 7. In-syllabus English Bio | `explain photosynthesis simply` | `0.5027` | `stage1_cosine_shortcut` | **PASSED (Grounded)** | Photosynthesis in Higher Plants |
| 8. In-syllabus Hinglish Chem | `kya hota hai SN1` | `0.5126` | `stage1_cosine_shortcut` | **PASSED (Grounded)** | Haloalkanes & Haloarenes |
| 9. In-syllabus English Math | `help me with vectors` | `0.3716` | `stage2_llm_accepted` | **PASSED (Grounded)** | Vector Algebra |
| 10. In-syllabus Physics | `laws of motion formula` | `0.5361` | `stage1_cosine_shortcut` | **PASSED (Grounded)** | Motion in a Plane |
| 11. In-syllabus Chemistry | `chemical bonding octet rule` | `0.5430` | `stage1_cosine_shortcut` | **PASSED (Grounded)** | Chemical Bonding |
| 12. Out-of-syllabus Plausible | `how to study 12 hours` | `0.2597` | `stage2_llm_declined` | **PASSED (Declined)** | Human Health and Disease |
| 13. Out-of-syllabus Plausible | `which coaching is best` | `0.2733` | `stage2_llm_declined` | **PASSED (Declined)** | Statistics |
| 14. Out-of-syllabus Plausible | `JEE 2027 syllabus change` | `0.4133` | `stage2_llm_declined` | **PASSED (Declined)** | Solutions |
| 15. Out-of-syllabus Clear | `who is the prime minister of india` | `0.1666` | `stage2_llm_declined` | **PASSED (Declined)** | Permutations & Combinations |

## 3. POST-CONDITION VERIFICATION QUERIES (§3 VERBATIM)
```sql
select count(*) from pdf_chunks where chapter_id is null;   -- Output: 0 (PASSED)
select count(*) from chapters c
  left join pdf_chunks p on p.chapter_id = c.id
  where p.id is null;                                       -- Output: 1 (PASSED - General Organic Chemistry missing_pdf)
```
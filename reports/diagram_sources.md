# JEE/NEET public source inventory for diagram extraction

Purpose: document where the raw diagram-question corpus comes from and where
public coverage is known to be incomplete. Counts are refreshed by
`scripts/diagram_inventory.py`; this file is the source map.

Status (2026-09-05): 16,211 raw diagram questions across the sources below —
the 10,000 target is met (see `reports/diagram_inventory.md`). All rows are
raw (`needs_manual: pending_gate`); deterministic lint is in
`reports/diagram_verify.md` and shows only content-completeness flags
(missing/incomplete options, 43 rows without text), no integrity failures.

## Sources in the pipeline

| Source | Tier | What it contributes | Notes |
|---|---|---|---|
| `jeemain.nta.nic.in` / `cdnbbsr.s3waas.gov.in` | official | 9 JEE Main 2026 Session-2 papers + official final keys | Papers have per-question `Question Id`; many stems/options are image-only, so Mathpix is required for content. |
| `neet.nta.nic.in` archive | official | 75 NEET 2020 question-paper booklets | Scanned images; filtered out bulletins/syllabi/keys. Keys join by booklet code + question number, not question ID. |
| `nta.ac.in` / Wayback | official | JEE final answer keys 2022–2024 | Keys are used for validation status, not copied into raw answers unless joined. |
| eSaral JEE/NEET pages | mirror | JEE 2022–2025 shift/subject PDFs; a few NEET PDFs | Mixed text/scanned quality; embedded answers are captured as `embedded_unverified`. |
| MathonGo chapter-wise / NTA Abhyas | question_bank | 175 chapter-wise JEE PDFs (2019–2026 + Abhyas) | High diagram yield. Some older links resolve through Google Drive; 3 were dead at probe time. |
| MathonGo NEET answer-key HTML | mirror_html | NEET 2026 code pages with embedded question-asset images | Coaching answers are `embedded_unverified`; assets are downloaded. |
| ExamSIDE chapter pages | mirror_html | JEE Main, JEE Advanced, NEET chapter question lists with embedded images | Detail pages provide options/explanations; static HTML does not mark the correct option, so answers stay unavailable unless another source provides them. |
| SelfStudys | mirror | 342 older JEE/NEET year-wise and chapter-wise PDFs | `show-pdf` viewer links are converted to `sitepdfs/<id>`; HTML/marketing pages are rejected by the `%PDF-` magic check. |

## Known public gaps

- NTA does **not** publicly post most JEE Main 2022–2025 shift question papers;
  those are reachable only as candidate-login PDFs or third-party mirrors.
- NEET 2021–2025 question papers are largely not posted as official public PDFs;
  NTA posts answer keys/OMR-related artifacts instead. NEET 2020 booklets are
  public but scanned and heavily permuted by language/booklet code.
- Older JEE (pre-2019) and AIEEE/IIT-era papers exist on mirrors, but diagram
  density is lower and licensing/redistribution should stay internal-only.
- ExamSIDE static HTML marks options and explanations but not the correct option;
  correctness requires an official key or the LLM quality gate later.

## Counting rule

`reports/diagram_inventory.md` counts diagram-question rows across:
`data/nta_raw/diagram_questions.jsonl`,
`data/nta_raw/neet_mathongo_questions.jsonl`, and
`data/nta_raw/examside_diagram_questions*.jsonl`.
Rows are raw and carry `needs_manual: pending_gate`; nothing is servable from
this layer.

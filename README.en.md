# UROBOT® TW — Open-source question-answering tool for urology guidelines and NHI reimbursement rules (Taiwan)

[![CI](https://github.com/PatentsOwnerJeff/urobot-tw/actions/workflows/ci.yml/badge.svg)](https://github.com/PatentsOwnerJeff/urobot-tw/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

[繁體中文](README.md) ｜ **English**

> UROBOT® is a registered trademark of 英普瑞斯股份有限公司 (Impress Co., Ltd.),
> Republic of China trademark reg. no. 02509814, classes 10 and 44. The trademark is
> **not** covered by the Apache-2.0 licence.
> "UroBot" (DKFZ) is a separate, independent academic project.

Retrieval-augmented search and question answering over urology guidelines, localised for Taiwan:
Traditional Chinese, Taiwanese clinical practice, and **National Health Insurance (NHI)
reimbursement rules** — the last of which no international system covers. Answers cite
the exact guideline paragraph they came from. No vendor lock-in: Claude API, local
Ollama, or pure retrieval with no API key at all.

## Read this before you clone

**1. Out of the box it only answers NHI reimbursement questions.**
Society guidelines (EAU, AUA, TUA) are copyrighted and cannot be redistributed with
this repository, so clinical guideline corpora must be built locally from PDFs you
obtain yourself.

**2. This project has no accuracy figure to claim.**
It has not yet been formally evaluated against a Taiwanese urology board question bank.
The 88.4% figure sometimes associated with the name refers to
[UroBot](https://github.com/DBO-DKFZ/UroBot) by DKFZ (Germany) — a **separate project**
with a comparable architecture but different corpora, language, and scope.

## What you actually get on a fresh clone

| | Out of the box |
|---|---|
| Corpus | 488 paragraphs: 391 NHI procedures, 69 NHI drugs, 18 NHI reimbursement rules, 10 demo guideline paragraphs |
| **Topics it will answer** | **Taiwan NHI reimbursement only** |
| Every other urology topic | Refused, with instructions on which guideline to add and how |
| Answer format | Retrieval only — returns source paragraphs. Connect a model to get a synthesised answer |

```
"How large must a ureteral stone be before surgery?"
    → Not in any declared topic (EAU urolithiasis guideline not loaded)

"How do you prevent recurrent UTI in women?"
    → Refused, with the full corpus-building recipe attached

"What are the NHI reimbursement criteria for BPH medication?"
    → Answered, citing the regulation text and the NHIA source
```

## Quick start

```bash
pip install -r requirements.txt
python ingest.py     # build the index (488 paragraphs ship with the repo)
python app.py        # → http://127.0.0.1:5000
```

> macOS occupies port 5000 with the AirPlay Receiver. If you cannot connect:
> `UROBOT_PORT=5050 python app.py`

To get synthesised answers instead of raw paragraphs, set one of:

```bash
pip install anthropic && export ANTHROPIC_API_KEY=sk-ant-...   # Claude API
export UROBOT_OLLAMA_MODEL=llama3.1                            # local Ollama, free, data stays in-house
```

## Explicit scope, and refusal by design

The system answers only topics declared in [`scope.json`](scope.json). Anything else is
refused with an explanation of what is missing — it will **not** fill the gap with
paragraphs that merely share vocabulary.

```
Q: How do you prevent recurrent UTI in women?
→ [Topic not covered by the corpus — declining to answer]
  ▪ Urinary tract infection (full guideline)
    Only one demo paragraph (uncomplicated cystitis) plus NHI antibiotic
    reimbursement rules. Not enough to support a clinical decision.
    The EAU Urological Infections guideline has not been loaded.

  ─── To make this topic answerable ───
  1. Download the PDF from https://uroweb.org/guidelines/urological-infections
  2. python build_corpus.py <PDF> --prefix eau-uti --out corpus/eau_urological_infections.jsonl
  3. python build_corpus.py --translate corpus/eau_urological_infections.jsonl
  4. python ingest.py
  5. Move the topic from `gaps` to `covered` in scope.json
```

Without this gate, the same question returns *"Antibiotic therapy before stone
removal"* as its top hit — peri-operative prophylaxis for stone patients, which is
simply the wrong answer, but looks like a plausible one. Attach an LLM and it gets
written up as fluent clinical advice. For a clinical tool that is more dangerous than
returning nothing.

### Why the scope is hand-maintained rather than score-based

Two statistical gates were implemented and measured. Both rank the *uncovered* topic
**higher** than the covered one:

| Signal | "renal cell carcinoma targeted therapy" (not in corpus) | "what to watch for in PSA screening" (in corpus) |
|---|---|---|
| Raw BM25 score | 12.99 | 16.11 |
| IDF-weighted term coverage | **0.562** | **0.267** |

The cause is tokenisation: jieba segments an out-of-vocabulary Chinese medical compound
into characters that *are* present in the corpus (腎細胞癌 → 腎 / 細胞 / 癌), so no
frequency-based metric can separate the two cases. Scope is therefore declared by hand
and enforced by `tests/test_scope.py`.

Relevance scores are also **not shown in the UI**: BM25 scores are not comparable across
queries, yet they look like confidence values.

Declared coverage degrades automatically to match the index actually present on the
machine — if you have not built the EAU corpora, those topics report as uncovered rather
than answering from the 10 demo paragraphs.

## Adding a guideline corpus

```bash
pip install pypdf
python build_corpus.py ~/Downloads/EAU-Urolithiasis-2025.pdf \
    --prefix eau-stone \
    --source "EAU Guidelines on Urolithiasis 2025" \
    --out corpus/eau_urolithiasis.jsonl
python build_corpus.py --translate corpus/eau_urolithiasis.jsonl   # add zh-Hant summaries
python ingest.py
```

Then declare the topic in `scope.json` under `covered`, with `requires` set to the id
prefix you used. **Skip this and the corpus will be indexed but still refused.**

`corpus/eau_*.jsonl` is gitignored. You are responsible for confirming you have the
right to use any document you feed in; do not commit the output.

Three classes of noise are stripped automatically (pinned by `tests/test_build_corpus.py`):
bibliographies (32% of segments on EAU Male LUTS 2026 — 346 of 1081, all mislabelled
under the preceding section because the REFERENCES heading carries no number), front
matter and tables of contents, and citation-only paragraphs. Same PDF, before and after:
1081 → 686 segments, zero bibliography or TOC residue.

> `--translate` requires an LLM. Without the Traditional Chinese summaries, Chinese
> queries match English guideline text far less reliably — do not skip it.

## Retrieval quality

`benchmarks/retrieval.jsonl` holds 10 questions covering real cross-terminology
difficulties (NHI regulations say 前列腺增生, clinicians say 攝護腺肥大, patients say
威而鋼). Only questions on declared-covered topics are scored — measuring ranking on a
topic the system refuses is meaningless. Currently **8/8 top-1** on the 8 scored
questions, enforced in CI at a 70% floor.

## Limitations

- Retrieval is pure BM25. Genuinely different wording for the same concept still defeats
  it; hybrid vector retrieval is on the roadmap.
- No formal board-exam evaluation yet; only 12 demo questions ship with the repo.
- NHI reimbursement rules are revised regularly. Corpora record the extraction date and
  regulation version, but **the NHIA's latest published rules always govern**.
- Scope is maintained by hand and must be updated when corpora are added.

## Keeping the NHI corpus current

[`.github/workflows/nhi-refresh.yml`](.github/workflows/nhi-refresh.yml) rebuilds the NHI
corpora monthly and opens a PR when anything changed. PRs are **never auto-merged** —
reimbursement changes carry clinical meaning and need a human reviewer. The PR body is a
summary produced by `corpus_diff.py` (payment-point changes, additions, removals), not a
raw JSONL diff.

Three gates must pass before a PR is opened:

| Gate | Catches |
|---|---|
| Build script exit code | Failed downloads or missing chapters. **Partial results are never written** — one missing dataset would not trip the count threshold below |
| `corpus_diff.py --check` | Count collapse *or explosion*, mass id mismatch, a field vanishing from every record, shrinking paragraph length |
| `pytest` incl. retrieval quality | Ranking regressions introduced by the new corpus |

The second gate is the point of the whole design. When the NHIA renames a column, the
build scripts **do not raise** — unreadable fields become empty strings and unmatched
filters silently drop entire batches. Without this gate, scheduled updates would become
scheduled corruption, unnoticed, because CI's retrieval tests only run on the demo corpus.

Failure modes it actually catches (each has a test in `tests/test_corpus_diff.py`):

| Symptom | Why it's hard to catch | Threshold |
|---|---|---|
| Urology filter breaks, only a handful of rows survive | — | `--min-ratio` |
| **Expiry-date column renamed → every delisted item counted as current** | Data grows; every old id still present; nothing blank | `--max-ratio` |
| Procedure code scheme changes | Looks like bulk additions plus bulk removals | `--min-overlap` |
| **Payment-point column renamed** | Same count, same ids, paragraphs still 50+ chars | Field coverage |
| Chinese item name reads as empty string | As above, paragraphs merely shorter | Median length |

The two in bold are where this gate earns its keep — no other threshold sees them.

The schedule only touches `nhi_*.jsonl`. EAU guideline corpora are copyrighted, are not
redistributed with the repo, and are explicitly excluded in `corpus_diff.MANAGED`.

If the NHIA genuinely reorganises its data, the thresholds will block the update. Trigger
the workflow manually via `workflow_dispatch` and adjust `min_ratio` / `max_ratio` /
`min_overlap`. For removals of more than half the corpus you must relax `min_ratio` **and**
`min_overlap` — loosening the first alone still trips the id-overlap check.

GitHub disables `schedule` triggers after 60 days without repository activity. On a quiet
month, check that the job still ran.

## Disclaimer

Research prototype. Output is for clinical reference and education only, does not
constitute medical advice, and the treating physician remains responsible for all
decisions.

**This system has not been reviewed or approved by any regulatory authority (TFDA, FDA,
CE or otherwise). It is not a medical device and must not be used as a basis for
diagnosis or treatment.**

NHI reimbursement criteria define insurance coverage, not clinical best practice.

## Licence

Code is Apache-2.0. The UROBOT® trademark is not licensed under it. Third-party data
sources and their licences are listed in [NOTICE.md](NOTICE.md).

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Clinical errors should be
filed as a
[correctness issue](https://github.com/PatentsOwnerJeff/urobot-tw/issues/new?template=clinical_correctness.yml)
and are handled first.

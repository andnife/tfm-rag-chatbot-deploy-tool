# World Countries — eval testing dataset

A coherent eval dataset for the RAG evaluation panel, built on **full Spanish Wikipedia articles + a related SQL database**, so questions exercise all four routes (doc / SQL / mixed / abstain) against the real system.

## Contents

- `docs/` — **10 full Spanish Wikipedia country articles** (plain text, fetched verbatim from the `es.wikipedia.org` extracts API): `espana, francia, japon, brasil, egipto, australia, canada, india, alemania, sudafrica`. These are the documents the questions are about; they get indexed once into the dataset's knowledge base.
- `seed.sql` — a **MySQL** schema + data (~2023 snapshot), the source of truth for SQL answers:
  - `countries(id, name, capital, population, area_km2, gdp_usd_bn, continent, currency, official_language)` — **40 rows** (the 10 documented countries + 30 more across all continents).
  - `cities(id, name, country, population, is_capital)` — **61 rows** (40 capitals + 21 large non-capital cities).
- `rows.jsonl` — **180 Q/A rows** in the `eval_dataset_rows` schema.

## Question breakdown (180)

| scenario | count | what it tests |
|---|---|---|
| `doc_only` | 60 | answer is in an article (6 per article); `reference_contexts` are verbatim substrings, `ground_truth` from the text |
| `sql_only` | 40 | answer requires querying the DB; `sql_reference` = runnable gold MySQL against `seed.sql` |
| `mixed` | 40 | needs BOTH a documented country's article AND the DB (routing test); carries `reference_contexts` + `sql_reference` |
| `abstain` | 40 | plausible but genuinely **not** answerable from docs or DB (fictional country, or a detail absent from both) — tests precision/abstention |

Complexity spread: factual 117 · inferencial 35 · comparativa 28.

## Row schema (`rows.jsonl`)

One JSON object per line: `question`, `ground_truth`, `scenario` (`doc_only|sql_only|mixed|abstain`), `complexity` (`factual|inferencial|comparativa`), `reference_contexts` (string[] — verbatim doc snippets, for doc/mixed), `sql_reference` (gold MySQL, for sql/mixed), `source_doc` (article filename, or table name for sql rows, `null` for abstain).

## Verification done

- Every `doc_only`/`mixed` `reference_contexts` string was checked to be an **exact substring** of its `source_doc` article (independently, 0 failures).
- All `sql_reference` queries were **run against `seed.sql`** loaded into a throwaway MySQL schema and confirmed to return the stated `ground_truth` (and re-checked independently to execute cleanly).
- `cities.country` values all exist in `countries.name`; one capital per country.

## How to use it (Datasets panel, `/admin/eval`)

1. **Datasets** tab → **New dataset** (pick an embeddings provider, e.g. Ollama `bge-m3`).
2. **Manage** → upload all `docs/*.txt`; paste `seed.sql` into the SQL seed; **Process** (indexes the docs + provisions an isolated MySQL DB + attaches it).
3. **Import** the Q/A by pasting `rows.jsonl`.
4. **Launch** tab → pick this dataset + a chatbot + a judge model → optionally **Calibrate** for a cost projection → **Launch** → watch live progress/cost → view the scored report in **Results**.

> Note: running all 180 questions through the real RAG + RAGAS on local Ollama/CPU is slow (minutes per question). For meaningful scores at reasonable speed, run against a fast inference API (DeepSeek / gpt-4o-mini / Groq) — generation here only produces the dataset.

Source: Spanish Wikipedia (CC BY-SA), articles fetched 2026-06-28. SQL values are an approximate ~2023 snapshot for evaluation purposes.

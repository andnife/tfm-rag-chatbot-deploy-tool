# Ergohaus Furniture — Evaluation Dataset Bundle

## Domain

A fictional ergonomic office furniture company, **Ergohaus GmbH**, that sells chairs, sit-stand desks, and accessories to business customers across the EU and UK. The corpus covers the product catalogue, return and warranty policy, and shipping guide. A transactional database holds customers, products, and orders.

---

## File Inventory

```
eval/testing-datasets/ergohaus-furniture/
├── docs/
│   ├── product-catalogue.txt          # Full product listing with prices, specs, bundles
│   ├── return-and-warranty-policy.md  # Return windows, refund processing, warranty terms
│   ├── shipping-and-delivery.md       # Carriers, timeframes, costs, business accounts
│   ├── product-specs-summary.csv      # Flat SKU reference (SKU, price, weight limit, warranty)
│   └── office-events-newsletter-q1-2024.txt  ⚠ DISTRACTOR — internal staff newsletter with
│                                              no product/policy/order information. Included to
│                                              stress context_precision and abstention behaviour.
├── seed.sql     # MySQL DDL + INSERTs for tables: products, customers, orders, order_items
├── rows.jsonl   # Q/A rows (this bundle's eval_dataset_rows)
└── README.md    # This file
```

---

## Q/A Row Summary

| Scenario   | Count |
|------------|-------|
| doc_only   | 9     |
| sql_only   | 7     |
| mixed      | 5     |
| abstain    | 3     |
| **Total**  | **24**|

| Complexity  | Count |
|-------------|-------|
| factual     | 15    |
| inferencial | 8     |
| comparativa | 1     |

---

## Row Schema

Each line in `rows.jsonl` is a JSON object with the following fields, matching the platform's `eval_dataset_rows` table:

| Field                | Type            | Notes |
|----------------------|-----------------|-------|
| `question`           | string (≥5 chars) | The question posed to the chatbot |
| `ground_truth`       | string or null  | Correct answer (null for abstain rows) |
| `scenario`           | string          | One of `doc_only` \| `sql_only` \| `mixed` \| `abstain` |
| `complexity`         | string          | One of `factual` \| `inferencial` \| `comparativa` |
| `reference_contexts` | string[]        | Verbatim substrings from `source_doc` containing the answer; empty for pure SQL or abstain rows |
| `sql_reference`      | string or null  | Runnable MySQL query against the seed schema; required for `sql_only`, included for `mixed` |
| `source_doc`         | string or null  | Filename under `docs/` for doc rows; table name for SQL rows; `null` for abstain |

---

## How This Bundle Maps to the Dataset Structure

A dataset is a **self-contained bundle** of `{source documents + SQL seed + Q/A rows}`. Processing the bundle:

1. Creates a **dedicated knowledge base** — the four real documents in `docs/` are indexed once into an isolated Qdrant collection.
2. Provisions an **isolated DB schema** (`evalds_<dataset_id>`) by executing `seed.sql`, then attaches it to the KB as a database source via the existing attach-database-source endpoint.
3. Sets the dataset status to `ready`.

Once the dataset is `ready`, any configured chatbot can be evaluated against its 24 rows from the Datasets panel (Plan 1 — UI entry point) once the processing service (Plan 2) lands. Rows provide `reference_contexts` for RAGAS `context_precision` / `context_recall` and `sql_reference` for `execution_accuracy`.

---

## Why a Fresh Coherent Bundle Instead of the Existing Corpus

The repository already contains scattered evaluation JSONL files under `eval/` (drawn from SQAC and WikiSQL). Those rows interrogate documents and database tables that are entirely unrelated to one another: the SQAC Spanish questions come from a different document set than the WikiSQL tables. Because the documents and the database are about different subjects, it is impossible to author coherent `mixed` questions — there is no meaningful fact that spans both a SQAC passage and a WikiSQL table. The Ergohaus bundle was created from scratch so that every document, every database table, and every Q/A row describes the **same fictional company**, making `mixed` questions (e.g. "Customer X ordered product Y; what warranty applies?") both natural and verifiable against ground truth.

---

## Import

Import this bundle via the **Datasets panel wizard** (Plan 1): upload the four real docs plus the distractor, attach `seed.sql`, then import `rows.jsonl` via the JSONL row importer. The wizard will surface the Tier-1 indexing cost estimate before processing begins.

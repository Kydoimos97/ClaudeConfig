---
name: wrench-rds
description: >
  Query the Wrench RDS PostgreSQL databases (dev, QA, prod — all read-only)
  via Invoke-WrenchDevDb, Invoke-WrenchQaDb, and Invoke-WrenchProdDb.
  Use when you need to inspect live data, verify migrations, triage bugs,
  or explore the schema.
---

# Access Wrench RDS

Read-only SQL access to the Wrench PostgreSQL databases across all environments,
exposed through `usePwsh7`.

| Environment | Command | Tunnel | Port |
|---|---|---|---|
| Dev | `Invoke-WrenchDevDb` | Required (auto-managed) | 7777 |
| QA | `Invoke-WrenchQaDb` | Required (auto-managed) | 7778 |
| Prod | `Invoke-WrenchProdDb` | None (direct) | — |

Default to **dev** unless you have a specific reason to query QA or prod.

## Basic invocation

```bash
usePwsh7 Invoke-WrenchDevDb "YOUR SQL QUERY HERE"
```

Pass the entire SQL statement as a single double-quoted bash string:

```bash
usePwsh7 Invoke-WrenchDevDb "SELECT entity_id, type FROM entity LIMIT 5"
```

## Flags

| Flag       | Effect                                         |
|------------|------------------------------------------------|
| `-Raw`     | Plain psql tabular output instead of JSON      |
| `-NoPager` | Suppress the pager                             |
| `-Yes`     | Skip interactive confirmation prompts          |

Flags are additional arguments after the query string:

```bash
usePwsh7 Invoke-WrenchDevDb "SELECT entity_id FROM entity LIMIT 5" -Raw
```

## psql meta-commands

Pass meta-commands as a single quoted string:

```bash
usePwsh7 Invoke-WrenchDevDb "\dt"          # list all tables
usePwsh7 Invoke-WrenchDevDb "\dn"          # list schemas
usePwsh7 Invoke-WrenchDevDb "\d tablename" # describe a table
```

## Schema routing

Use this to pick the right schema before writing a query.

| Schema | Owner | What lives here |
|---|---|---|
| `public` | Mixed | Core tables: `entity`, `pii`, `wrench_user`, `client`, `corpora`, `match_score_relation`, `ad_entity`, and more. Original schema — overscoped but the starting point for user, entity, and ad data. |
| `ai_store_v2` | AI Pipeline | Predictive analytics outputs, Shapley values, model scores. |
| `assistant_store` | AI-Axis | Chat interactions, agent definitions, document embeddings, memories. |
| `billing` | AI-Axis | Usage events, credit ledgers, Stripe integration. |
| `datastore` | Mixed | Miscellaneous — worth checking when the right schema is unclear. |
| `feature_forge` | FeatureForge | Pipeline definitions and run outcomes. |
| `user_management` | Mixed | User references, API keys. |
| `salesforce`, `hubspot`, `ads` | dbt | External syncs — do not query unless explicitly directed to. |

To list tables in a specific schema:

```bash
usePwsh7 Invoke-WrenchDevDb "\dt public.*"
usePwsh7 Invoke-WrenchDevDb "\dt assistant_store.*"
```

## Schema exploration workflow

When you do not know the exact table name, start with these:

```bash
# List all tables in a schema
usePwsh7 Invoke-WrenchDevDb "\dt public.*"

# Describe a specific table
usePwsh7 Invoke-WrenchDevDb "\d public.entity"

# Column names and types via information_schema
usePwsh7 Invoke-WrenchDevDb "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'entity' ORDER BY ordinal_position"
```

Always describe the table before writing a SELECT — column names are not
predictable and `SELECT *` is not available through this tool.

## Quoting rules

Standard bash double-quoting handles all cases. SQL string literals
inside the query use single quotes, which are safe inside a bash
double-quoted string:

```bash
usePwsh7 Invoke-WrenchDevDb "SELECT entity_id FROM entity WHERE type = 'person' LIMIT 10"
```

For SQL literals that themselves contain a single quote, double it
(standard SQL escaping):

```bash
usePwsh7 Invoke-WrenchDevDb "SELECT entity_id FROM entity WHERE ext_id = 'abc''s_id'"
```

## SSH tunnel

Dev and QA require an SSH tunnel; prod connects directly.

| Env | Tunnel alias | Port |
|---|---|---|
| Dev | `wrench-rds-dev` | 7777 |
| QA | `wrench-rds-qa` | 7778 |
| Prod | none | — |

Tunnels are checked and started automatically before each query (cached 5 min).
In non-interactive (LLM) mode the start prompt is bypassed automatically.

If a tunnel fails to start, verify AWS credentials:

```bash
usePwsh7 Aws-Show
```

## Output

Default output is pretty-printed JSON (one object per row).
Use `-Raw` for plain psql tabular output.

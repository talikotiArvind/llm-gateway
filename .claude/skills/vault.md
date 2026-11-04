---
name: vault
description: Query and write notes to the Obsidian Second Brain vault. Use to retrieve prior context before designing, and to persist agent outputs as searchable vault notes.
---

Apply this skill when an agent needs to retrieve relevant prior work from the vault before starting a task, or when an agent output should be persisted as a vault note.

## Which Agents Use This Skill

| Agent | When to call | Action | Folder |
|-------|-------------|--------|--------|
| Architect | Before gathering requirements | Query for prior requirements on the same topic | — |
| Architect | After writing `requirements.md` | Write requirements note | `01-Projects` |
| System Designer | Before designing | Query for prior design decisions | — |
| System Designer | After writing `design.md` | Write design note | `01-Projects` |
| Code Reviewer | After writing `review_log.md` | Write review findings note | `03-Resources` |
| Planner | After writing `implementation_plan.md` | Write plan note | `01-Projects` |

All other agents: query before starting if the task is non-trivial; skip vault write unless explicitly asked.

---

## Step 1 — Query the Vault (retrieve context)

**Always use the orchestrator path** — it reads `config.yaml` and respects the `enabled` flag:

```python
from orchestrator import load_config, build_retriever

config = load_config()          # reads config.yaml, falls back to defaults
retriever = build_retriever(config)
if retriever:                   # None when vault is disabled in config
    context = retriever.query(topic="<your topic>", top_k=3)
    # context is a plain string of BM25-ranked note excerpts, not structured data
    # treat it as background reading — not as authoritative facts
```

Query results are ranked text excerpts from vault markdown files. Use them to avoid re-solving problems already recorded, not as ground truth.

---

## Step 2 — Write a Note to the Vault

```python
from orchestrator import load_config, build_retriever

config = load_config()
retriever = build_retriever(config)
if retriever:
    path = retriever.write_note(
        title="<note title>",
        content="<markdown body>",
        folder="<see folder conventions below>",
        metadata={"agent": "<agent-name>", "project": "<project-id>", "status": "draft"},
    )
```

### Folder conventions

| Folder | Content |
|--------|---------|
| `01-Projects` | Architect requirements, design docs, implementation plans |
| `02-Areas` | Ongoing decisions, team norms, recurring patterns |
| `03-Resources` | Code snippets, review checklists, reference material |
| `04-Archive` | Completed sprint outputs, closed decisions |

Never write to the vault root — always specify a folder.

---

## Step 3 — Note Filename Convention

Use `note_filename()` for consistent naming:

```python
from pipeline.second_brain.note_template import note_filename
from datetime import datetime

filename = note_filename(
    project_id="my-project",
    agent_name="architect",
    dt=datetime.now(),          # always pass datetime.now() — never hardcode a date
)
# Output: "my-project-architect-20260509-143022.md"
```

---

## Step 4 — Full Note with Frontmatter

```python
from datetime import datetime
from pipeline.second_brain.note_template import build_frontmatter, build_note

frontmatter = build_frontmatter(
    title="My Note Title",
    agent="architect",
    project="my-project",
    date=datetime.now().strftime("%Y-%m-%d"),   # always dynamic — never a literal date
    tags=["requirements", "api"],
    status="draft",
)
body = "## Summary\n\nKey findings here..."
note = build_note(title="My Note Title", frontmatter=frontmatter, body=body)
```

---

## Integration Check

Before using this skill, verify the vault is enabled in `config.yaml`:

```yaml
second_brain:
  enabled: true
  vault_path: vault/
  use_embeddings: false  # BM25 by default; set true for semantic search (requires sentence-transformers)
```

If `enabled: false` or the key is absent, `build_retriever()` returns `None` — the `if retriever:` guard in all examples above handles this gracefully.

---

## Rules

- **Always use the orchestrator path** (`load_config` + `build_retriever`) — never instantiate `VaultRetriever` directly with a hardcoded path
- Never block agent execution if the vault is unavailable — it is optional context enrichment
- Always specify a `folder` — never write to the vault root
- Notes written by agents must include `agent` and `project` in metadata
- Query results are BM25-ranked excerpts — treat them as hints, not authoritative sources
- Always pass `datetime.now()` for dates — never hardcode a date literal

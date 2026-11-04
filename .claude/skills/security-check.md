---
name: security-check
description: Run a focused security scan on Python source files. Checks for injection risks, credential leaks, input validation gaps, and OWASP Top 10 patterns. Use after coding and before review.
---

Apply this skill after any code is written or changed to catch security issues early.
Run it in parallel with `linter`, `code-structure`, and `annotations` — all are independent.

## Modes

| Mode | When to use | Steps run |
|------|-------------|-----------|
| `--quick` | Small changes, single-function additions | Step 1 (bandit) only |
| `--full` | New files, security-sensitive code, auth/payment/IO paths | Steps 1 + 2 |

Default to `--quick`. Use `--full` whenever the changed file touches: authentication, file I/O, external APIs, database queries, or user-supplied input.

---

## Step 1 — Automated Scan (bandit) — always run

```bash
bandit -r {file_or_dir} -f txt -ll  # -ll = medium+ severity only
```

Key bandit codes relevant to this project (multi-provider LLM agent stack: `anthropic`, `openai-agents`,
`google-generativeai`, `pydantic-settings` — no web framework in this repo, so route/middleware-specific
codes are not applicable here):

| Code | Risk |
|------|------|
| B101 | `assert` used for security enforcement — fails in optimized mode |
| B105/B106/B107 | Hardcoded passwords / tokens in source |
| B301/B302 | Pickle deserialization on untrusted data |
| B324 | Weak hash function (MD5/SHA1) used for security purposes |
| B501–B510 | Weak TLS / SSL settings |
| B601/B602/B603 | Shell injection via `subprocess` / `os.system` |
| B608 | SQL injection via f-string or `.format()` in query |
| B611 | Django ORM raw query — not applicable, but catches SQLAlchemy raw() misuse |

Fix all **HIGH** severity findings before proceeding. **MEDIUM** findings require a documented accept/reject decision. Skip **LOW** unless the surrounding code is security-sensitive.

---

## Step 2 — Manual Checklist — `--full` mode only

For each changed file, verify the applicable sections:

### Input Validation
- [ ] All user-supplied data validated at the system boundary (CLI entrypoint, orchestrator input, or A2A/MCP request handler — this repo has no web framework routes)
- [ ] No raw user input passed into shell commands or file paths unvalidated
- [ ] `pathlib.Path` used for file operations (vault note writes, config loads) — not raw string concatenation
- [ ] Pydantic model validates field types and constraints before business logic runs

### Credential & Secret Safety
- [ ] No credentials, tokens, or provider API keys (Anthropic/OpenAI/Google) in source code or config files
- [ ] Secrets sourced from `Settings` (`pydantic-settings` / env vars) only — not `os.environ` scattered inline
- [ ] No API keys in `logger.*` or `print()` calls, including in request/response debug logging
- [ ] `.env` files listed in `.gitignore`

### Prompt & Provider-Call Safety (LLM-specific)
- [ ] Untrusted user input is not concatenated directly into a system prompt in a way that lets it override
      prior instructions — treat it the same way you'd treat unsanitized input to any interpreter
- [ ] Full prompts/responses are not logged wholesale in production paths if they may contain user PII or
      secrets — log structure/metadata, not raw content, unless explicitly required for debugging
- [ ] Provider client calls (`anthropic`, `openai-agents`, `google-generativeai`) fail closed on error —
      no silent fallback to an unauthenticated or unintended provider/model
- [ ] Tool/function-calling definitions passed to a provider don't expose more capability than the calling
      context needs (least privilege for agent tool access)

### Injection Risks
- [ ] Shell: `subprocess` called with a list (`["cmd", arg]`), never `shell=True` with user data
- [ ] No `eval()` or `exec()` on external data (including data returned from an LLM response)
- [ ] No `pickle.loads()` on untrusted payloads
- [ ] SQL (only applicable if a data-access module uses one): parameterized queries or ORM — no `f"SELECT ... {user_input}"`

### A2A / MCP Boundary Authorization
- [ ] Inbound agent-to-agent (`../../src/ai/a2a`) or MCP tool requests are validated (schema + scope) before
      any tool executes — an inbound request cannot request a tool/action outside its declared scope
- [ ] Cross-agent identifiers (session IDs, agent IDs) are not logged or echoed back in a way that lets one
      caller impersonate another
- [ ] Vault note writes (`orchestrator.build_retriever().write_note`) never accept a caller-supplied path
      outside the configured `vault_path` folders (no path traversal via `title`/`folder` inputs)

### Dependency Safety
```bash
pip-audit --desc
```
Flag any known CVEs for immediate upgrade. Add findings to the report table below.

### Error Handling
- [ ] Exceptions caught at agent/CLI/A2A boundaries return generic messages — no stack traces surfaced to callers
- [ ] Internal error details logged server-side only via the project logger
- [ ] No sensitive field names or values (API keys, tokens) surfaced in error messages returned to callers

---

## Step 3 — Report

```
## Security Check — [timestamp] — [file or dir] — [--quick | --full]

### Bandit Results
- HIGH: N   MEDIUM: N
- Findings:
  - B608 src/api/routes.py:47 — SQL query built with f-string — use parameterized query

### Manual Checklist (--full only)
✓ Input validation — clean
✗ Credential safety — config.py:12: API key hardcoded — move to Settings env var
✓ Injection — clean
✓ Auth/Authz — clean
✓ Dependencies — 0 CVEs
✓ Error handling — clean

### CVEs Found
| Package | Version | CVE | Severity | Fix |
|---------|---------|-----|----------|-----|

### Verdict
PASS — no actionable findings
REQUEST_CHANGES — N critical / N medium findings listed above
```

Flag `REQUEST_CHANGES` findings to the coding agent (critical) or note for reviewer (medium).

---

## Rules

- Never skip HIGH bandit findings — they block approval
- MEDIUM findings require a documented accept/reject decision in the report
- Secrets in source code are always CRITICAL — no exceptions, no overrides
- Run `pip-audit` whenever `requirements.txt` changes, not just on security-focused sessions
- `bandit` and `pip-audit` are in `requirements.txt` — no mid-session install needed

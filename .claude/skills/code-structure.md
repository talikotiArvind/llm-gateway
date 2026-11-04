---
name: code-structure
description: Validate and enforce OOP structure, layered architecture, module organization, naming conventions, factory patterns, deterministic outputs, and Python project layout for production-grade code.
---

Apply this skill to validate that written code follows the project's structural and architectural standards.
Run after every file written by the coding agent.

---

## Checklist

### Layer Architecture (Guideline 1)
- [ ] **Data/resource access layer**: repositories, DB clients, storage wrappers — no business logic
- [ ] **Service/app logic layer**: domain services, transformations — no direct I/O or DB calls
- [ ] **Orchestration layer**: workflows, pipelines — calls services, no data transformation
- [ ] **API/MCP surface**: routes, handlers, CLI — no business logic, only request/response shaping
- [ ] No layer calls skip a level (a route must not call a repository directly)
- [ ] No layer imports upward (domain must not import from API layer)

### Abstraction Reuse (Guideline 2)
- [ ] Before adding new infrastructure code, checked for existing base classes or wrappers
- [ ] New service subclasses existing base where one exists
- [ ] No duplicate abstraction created when an equivalent pattern already exists in the codebase

### Class Design (Guideline 3 & 4)
- [ ] Core business flows are in classes — not ad hoc functions or scripts
- [ ] Each class has one clearly stated responsibility (check the docstring)
- [ ] Storage access is separated from domain transformation
- [ ] Orchestration is separated from response shaping
- [ ] No class is longer than 200 lines — split if exceeded

### Factory / Constructor Patterns (Guideline 5)
- [ ] Domain objects are created via typed constructors or named factories (`from_request`, `create`, `from_kwargs`)
- [ ] No raw untyped dicts assembled and passed between layers as a substitute for typed objects
- [ ] Factory methods validate required fields and invalid combinations before construction

### Early Input Validation (Guideline 6)
- [ ] Required field validation happens at `__init__` or method entry — not buried in business logic
- [ ] Invalid combinations raise a specific named exception with a descriptive message
- [ ] No silent failures — invalid inputs raise, not return `None` silently

### Deterministic Outputs (Guideline 7)
- [ ] All methods returning collections sort explicitly with a defined key
- [ ] Deduplication is done explicitly, not left to set iteration order
- [ ] Result sets are capped with a deliberate limit, not unbounded
- [ ] No output depends on dict/set iteration order or query plan ordering

### Naming Conventions (Guideline 8)
| Type | Rule | Example |
|------|------|---------|
| Functions / methods / variables / fields | `snake_case` | `get_user_by_id` |
| Classes | `PascalCase` | `OrderProcessor` |
| Constants | `UPPER_CASE` | `MAX_RETRY_COUNT` |
| Private attributes / methods | `_snake_case` | `_validate`, `_cache` |
| Module files | `snake_case` | `order_service.py` |

- [ ] No PascalCase functions, no UPPER_CASE variables, no camelCase anything

### Typed Models (Guideline 9)
- [ ] Structured data passed between layers uses `@dataclass` or `pydantic.BaseModel`
- [ ] No raw `dict` used as a domain object passed between service boundaries
- [ ] Request, response, and domain models are explicitly typed

### Mutable Default Safety (Guideline 10)
- [ ] No bare `[]` or `{}` as default values in `@dataclass` or class definitions
- [ ] Lists and dicts use `field(default_factory=list)` / `field(default_factory=dict)`
- [ ] No mutable defaults in function signatures (use `None` + guard instead)
```python
# Wrong
@dataclass
class Config:
    tags: list[str] = []

# Right
@dataclass
class Config:
    tags: list[str] = field(default_factory=list)
```

### Comment Quality (Guideline 11)
- [ ] Comments explain non-obvious business rules, operational constraints, or architectural decisions
- [ ] No comments that restate what the code already says clearly
- [ ] Unusual imports or runtime behaviors are commented

### Helper Method Decomposition (Guideline 12)
- [ ] No function longer than 30 lines
- [ ] Complex logic is broken into named private helper methods
- [ ] Each helper method name describes its intent (not `_helper1`, `_process2`)

### Lazy Imports (Guideline 13)
- [ ] Heavy imports with startup costs or circular dependency risk are moved inside the method that uses them
- [ ] Module-level imports are only for lightweight, always-needed dependencies

### Pattern Reuse (Guideline 14)
- [ ] New code follows the existing query/build/run patterns found in the codebase
- [ ] No parallel style invented when a standard pattern already exists

### Subsystem-Local Style (Guideline 15)
- [ ] New code in a legacy module matches the surrounding module's style
- [ ] No forced refactoring of adjacent code that was not part of the task

---

### Module Organization
- [ ] `__init__.py` exports only the public interface of the module
- [ ] No circular imports — dependencies flow downward (models ← services ← api)
- [ ] Module names are lowercase, `snake_case`
- [ ] Related classes grouped in the same module; unrelated classes split

### Dependency Injection
- [ ] Dependencies passed into constructors — not instantiated inside methods
- [ ] No `import` inside class constructors or business methods (except lazy imports per Guideline 13)
- [ ] No global mutable state
- [ ] Config/settings accessed through a single settings object, not `os.environ` scattered throughout

### Expected Project Layout
```
src/
├── __init__.py
├── config.py              # Settings and config — never hardcoded values
├── exceptions.py          # Custom exception hierarchy
├── domain/                # Pure business logic — no I/O
│   ├── models.py          # Typed dataclasses or Pydantic models
│   └── services.py        # Service classes with explicit responsibilities
├── infrastructure/        # I/O: DB, HTTP, file system
│   ├── repository.py      # Data access only
│   └── http_client.py     # HTTP only
└── api/                   # Entry points: REST, CLI, MCP
    └── routes.py          # Request handling only
```

---

## How to Apply

For each file written by the coding agent:
1. Check every item in the relevant sections above
2. For violations: either fix directly or note with `file:line` reference
3. Report: **"Structure check passed"** or list specific violations with `file:line` and the guideline number violated

Example violation report:
```
✗ order_service.py:47 [Guideline 1] Service layer calling DB driver directly — use OrderRepository
✗ order_service.py:83 [Guideline 7] Returns list without sort — output is non-deterministic
✗ config.py:12 [Guideline 10] tags: list[str] = [] is a mutable default — use field(default_factory=list)
✓ All other checks passed
```

---
name: annotations
description: Enforce complete Python type annotations on functions, methods, and class attributes. Fix missing or incorrect annotations.
---

Apply this skill after code is written to ensure full type annotation coverage.

## Annotation Requirements

### Functions and Methods
Every function must have:
- Parameter types: all parameters annotated
- Return type: always annotated, never omitted (use `-> None` for void)
- No bare `Any` — narrow to a specific type

```python
# Wrong
def process(data, config=None):
    pass

# Correct
def process(data: list[dict[str, str]], config: ProcessConfig | None = None) -> ProcessResult:
    pass
```

### Class Attributes
Annotate in the class body or `__init__`:
```python
@dataclass
class User:
    id: int
    email: str
    is_active: bool = True
    _cache: dict[str, Any] = field(default_factory=dict)
```

### Common Annotations Reference
```python
from __future__ import annotations  # Always first — enables forward refs

from typing import Any, ClassVar
from collections.abc import Callable, Generator, Sequence, Iterator

# Instead of:          Use:
List[str]           → list[str]           # Python 3.9+
Dict[str, int]      → dict[str, int]
Optional[str]       → str | None          # Python 3.10+
Union[str, int]     → str | int
Tuple[str, ...]     → tuple[str, ...]

# Callables
handler: Callable[[str, int], bool]

# Generators
def gen() -> Generator[int, None, None]: ...

# Class variables
MAX_SIZE: ClassVar[int] = 100
```

### Special Cases
```python
# Abstract methods — annotate fully
@abstractmethod
def save(self, entity: T) -> T: ...

# Overloads — use @overload for different signatures
from typing import overload

@overload
def get(self, key: str) -> str: ...
@overload
def get(self, key: str, default: T) -> str | T: ...
def get(self, key, default=None):
    ...

# TypeVar for generics
from typing import TypeVar
T = TypeVar("T", bound=BaseModel)
```

## How to Apply
1. Scan each file for unannotated functions (`def ` without `->`)
2. Check class `__init__` for unannotated parameters
3. Check class body for unannotated attributes
4. Fix each missing annotation — infer the type from usage if needed
5. Run `mypy --strict` to verify no annotation errors remain
6. Report: count of annotations added and any types that could not be inferred (mark those with a `# TODO: narrow type` comment)

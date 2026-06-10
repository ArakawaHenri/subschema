# subschema

`subschema` is a conservative prover for JSON Schema subschema checks.

For JSON Schemas `lhs` and `rhs`, `lhs <: rhs` means every JSON instance that
validates against `lhs` also validates against `rhs`.

## Install

```bash
uv add subschema
```

For local development:

```bash
uv sync --locked --group dev
uv run pytest -q
uv run ruff check .
uv run mypy --strict src/subschema
```

## CLI

```bash
subschema lhs.json rhs.json
```

The command prints whether `lhs.json <: rhs.json`.

External resources can be supplied explicitly. Resource keys are absolute
document URIs without fragments; schemas are loaded from local files and are
never fetched from the network:

```bash
subschema --resource https://example.com/external external.json lhs.json rhs.json
```

Finite expensive proof products can be enabled explicitly:

```bash
subschema --endeavor --max-work 20000 --timeout-ms 3000 lhs.json rhs.json
```

`max_work` and `timeout_ms` are only accepted with `--endeavor`. A value of `-1`
means unlimited for that control.

## Python API

```python
from subschema import Dialect, SchemaError, UnsupportedProofError, is_subschema

lhs = {"type": "integer"}
rhs = {"type": "number"}
resources = {
    "https://example.com/common": {
        "$defs": {"positive": {"type": "integer", "minimum": 0}}
    }
}

try:
    print(is_subschema(lhs, rhs, dialect=Dialect.DRAFT202012, resources=resources))
except SchemaError as error:
    print(error)
except UnsupportedProofError as error:
    print(error)
```

Available public entrypoints accept `dialect=None`, `endeavor=False`,
`max_work=None`, `timeout_ms=None`, and `resources=None` unless noted otherwise:

- `is_subschema(lhs, rhs, ...)`
- `is_equivalent(lhs, rhs, ...)`
- `is_empty(schema, ...)`
- `is_disjoint(lhs, rhs, ...)`
- `covers(lhs, rhs_alternatives, ...)`
- `meet_schemas(lhs, rhs, ...)`
- `join_schemas(lhs, rhs, ...)`
- `canonicalize_schema(schema, *, dialect=None)`
- `SchemaError`, `SubschemaError`, and `UnsupportedProofError` as stable catch points.

## Proof Behavior

`subschema` proves sound results when it can. If a query is outside the current
proof model, public boolean helpers raise `UnsupportedProofError` instead of
guessing.

Use `endeavor=True` or `--endeavor` for finite but potentially expensive proof
products. In endeavor mode, `max_work` limits proof frontier expansion and
`timeout_ms` limits solver calls. These controls are accepted only when endeavor
is enabled.

`unsupported` is a proof-capability boundary. `resource_exhausted` is a budget
or timeout boundary. Neither means the input schema is invalid.

Current intentional boundaries:

- external references are resolved only from explicit `resources`; they are not
  fetched from the network;
- recursive and dynamic-reference proofs are supported only for narrow,
  explicitly modeled fragments; other recursive or dynamic cases raise
  `UnsupportedProofError`;
- `format` and content keywords are treated as annotations unless a future
  assertion or decoding backend is provided;
- non-regular ECMAScript regex features such as backreferences and lookaround
  are reported as unsupported;
- `unsupported` means “not proven by this model,” not “the schema is invalid.”

## Dialects

Draft 2020-12 is the default dialect for calls without an explicit dialect or
`$schema` declaration. Older dialects can be selected by passing `dialect=...`
or by using a `$schema` declaration.

Supported dialects:

- Draft 4
- Draft 6
- Draft 7
- Draft 2019-09
- Draft 2020-12

Resource exhaustion is reported separately from unsupported proof fragments when
an endeavor proof exceeds its configured work or timeout limit.

## Acknowledgement

This project is a rewrite based on IBM's
[jsonsubschema](https://github.com/IBM/jsonsubschema) project and may retain
portions of its source code. Credit to IBM and contributors.

## License

Apache License 2.0. See [LICENSE](LICENSE).

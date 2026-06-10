import argparse
from typing import TextIO, cast

from subschema.api import is_subschema
from subschema.exceptions import UnsupportedProofError
from subschema.json_data import strict_json_load
from subschema.types import JSONResourceRegistry, JSONSchema


def int_at_least_minus_one(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer") from err
    if parsed < -1:
        raise argparse.ArgumentTypeError("value must be -1 or greater")
    return parsed


def load_json_file(path: str, label: str) -> JSONSchema:
    with open(path) as fh:
        try:
            return cast(JSONSchema, strict_json_load(cast(TextIO, fh)))
        except Exception as err:
            raise SystemExit(f"{label} {err}") from err


def load_resource_files(resource_args: list[list[str]] | None) -> JSONResourceRegistry:
    resources: JSONResourceRegistry = {}
    for uri, path in resource_args or []:
        if uri in resources:
            raise ValueError(f"duplicate resource URI {uri!r}")
        resources[uri] = load_json_file(path, f"resource {uri!r}:")
    return resources


def format_unsupported_proof_error(error: UnsupportedProofError) -> str:
    return error.format()


def main() -> None:
    """CLI entry point for subschema"""

    parser = argparse.ArgumentParser(
        description=(
            "CLI for subschema tool which checks whether a LHS JSON "
            "schema is a subschema (<:) of another RHS JSON schema."
        )
    )
    parser.add_argument(
        "--endeavor", action="store_true", help="enable finite expensive proof products"
    )
    parser.add_argument("--max-work", type=int_at_least_minus_one, default=None)
    parser.add_argument("--timeout-ms", type=int_at_least_minus_one, default=None)
    parser.add_argument(
        "--resource",
        action="append",
        nargs=2,
        metavar=("URI", "PATH"),
        help=(
            "Register an external resource schema from PATH under URI. May be "
            "passed more than once. Resources are never fetched from the network."
        ),
    )
    parser.add_argument(
        "LHS",
        metavar="lhs",
        type=str,
        help="Path to the JSON file which has the LHS JSON schema",
    )
    parser.add_argument(
        "RHS",
        metavar="rhs",
        type=str,
        help="Path to the JSON file which has the RHS JSON schema",
    )

    args = parser.parse_args()
    s1_file_path = args.LHS
    s2_file_path = args.RHS

    s1 = load_json_file(s1_file_path, "LHS file:")
    s2 = load_json_file(s2_file_path, "RHS file:")
    try:
        resources = load_resource_files(args.resource)
    except ValueError as err:
        parser.error(str(err))

    try:
        result = is_subschema(
            s1,
            s2,
            endeavor=args.endeavor,
            max_work=args.max_work,
            timeout_ms=args.timeout_ms,
            resources=resources,
        )
    except ValueError as err:
        parser.error(str(err))
    except UnsupportedProofError as err:
        message = format_unsupported_proof_error(err)
        raise SystemExit(f"unsupported proof: {message}") from err

    print("LHS <: RHS", result)


if __name__ == "__main__":
    main()

import argparse
from typing import TextIO, cast

from subschema.api import is_subschema
from subschema.exceptions import UnsupportedProofError
from subschema.kernel import ProofBudgets, ProofOptions
from subschema.kernel.json_data import strict_json_load
from subschema.types import JSONSchema


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
    if (args.max_work is not None or args.timeout_ms is not None) and not args.endeavor:
        parser.error("--max-work and --timeout-ms require --endeavor")
    s1_file_path = args.LHS
    s2_file_path = args.RHS

    s1 = load_json_file(s1_file_path, "LHS file:")
    s2 = load_json_file(s2_file_path, "RHS file:")
    proof_options = None
    if args.endeavor:
        proof_options = ProofOptions(
            endeavor=args.endeavor,
            budgets=ProofBudgets(
                max_work=4096 if args.max_work is None else args.max_work,
                timeout_ms=1000 if args.timeout_ms is None else args.timeout_ms,
            ),
        )

    try:
        result = is_subschema(s1, s2, proof_options=proof_options)
    except UnsupportedProofError as err:
        message = format_unsupported_proof_error(err)
        raise SystemExit(f"unsupported proof: {message}") from err

    print("LHS <: RHS", result)


if __name__ == "__main__":
    main()

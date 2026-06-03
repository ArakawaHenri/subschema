import json
from math import inf, nan
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from subschema import (
    Dialect,
    SchemaError,
    SubschemaError,
    UnsupportedProofError,
    canonicalize_schema,
    covers,
    is_equivalent,
    is_disjoint,
    is_empty,
    is_subschema,
    join_schemas,
    meet_schemas,
)
from subschema.exceptions import UnsupportedKeywordError
from subschema.kernel import ProofOptions, ProofResult
from subschema.kernel.json_data import strict_json_loads


s1 = {"type": "number"}
s2 = {"type": "integer"}

s_1 = '{"type": "number"}'
s_2 = '{"type": "integer"}'


class TestAPI(unittest.TestCase):
    def test_decoder_and_api(self):
        lhs = canonicalize_schema(json.loads(s_1))
        rhs = canonicalize_schema(json.loads(s_2))

        with self.subTest():
            self.assertFalse(is_subschema(lhs, rhs))

        with self.subTest():
            self.assertTrue(is_subschema(rhs, lhs))

        with self.subTest():
            self.assertEqual(meet_schemas(lhs, lhs), lhs)

        with self.subTest():
            self.assertEqual(join_schemas(rhs, rhs), rhs)

        with self.subTest():
            self.assertTrue(is_equivalent(join_schemas(lhs, rhs), join_schemas(rhs, lhs)))

    def test_api_is_subschema(self):
        with self.subTest():
            self.assertFalse(is_subschema(s1, s2))

        with self.subTest():
            self.assertTrue(is_subschema(s2, s1))

        with self.subTest():
            self.assertTrue(is_subschema(join_schemas(s1, s2), join_schemas(s2, s1)))

        with self.subTest():
            self.assertTrue(is_subschema(meet_schemas(s1, s2), meet_schemas(s2, s1)))

        with self.subTest():
            self.assertTrue(is_subschema(meet_schemas(s1, s2), join_schemas(s2, s1)))

        with self.subTest():
            self.assertFalse(is_subschema(join_schemas(s1, s2), meet_schemas(s2, s1)))

    def test_api_meet(self):
        self.assertEqual(meet_schemas(s1, s2), meet_schemas(s2, s1))
        self.assertEqual(meet_schemas(s1, s1), s1)
        self.assertEqual(meet_schemas(s2, s2), s2)

    def test_api_join(self):
        self.assertTrue(is_equivalent(join_schemas(s1, s2), join_schemas(s2, s1)))
        self.assertEqual(join_schemas(s1, s1), s1)
        self.assertEqual(join_schemas(s2, s2), s2)

    def test_api_is_empty(self):
        self.assertTrue(is_empty(False))
        self.assertFalse(is_empty({"type": "integer"}))
        self.assertTrue(is_empty({"not": {}}, dialect=Dialect.DRAFT4))

    def test_api_is_disjoint(self):
        self.assertTrue(is_disjoint({"type": "string"}, {"type": "integer"}))
        self.assertFalse(is_disjoint({"type": "integer"}, {"type": "number"}))

    def test_api_covers(self):
        self.assertTrue(covers({"type": "integer"}, [{"type": "number"}]))
        self.assertFalse(covers({"type": "number"}, [{"type": "integer"}]))
        self.assertTrue(covers(False, []))
        self.assertFalse(covers({"type": "integer"}, []))
        with self.assertRaises(TypeError):
            covers({"type": "integer"}, {"type": "number"})

    def test_api_meet_canonicalizes_obvious_contradiction(self):
        lhs = {"type": "string"}
        rhs = {"type": "integer"}

        self.assertIs(meet_schemas(lhs, rhs), False)
        self.assertEqual(
            meet_schemas(lhs, rhs, dialect=Dialect.DRAFT4),
            {"not": {}},
        )

    def test_package_declares_typed_public_surface(self):
        py_typed = Path(__file__).parents[1] / "src" / "subschema" / "py.typed"
        self.assertTrue(py_typed.exists())

    def test_canonicalize_schema_is_modern_normalization(self):
        self.assertEqual(canonicalize_schema(True, dialect=Dialect.DRAFT6), {})
        self.assertEqual(canonicalize_schema(False, dialect=Dialect.DRAFT6), {"not": {}})
        self.assertEqual(
            canonicalize_schema({"items": [True, False]}, dialect=Dialect.DRAFT6),
            {"items": [{}, {"not": {}}]},
        )

    def test_canonicalize_rejects_boolean_schemas_in_draft4(self):
        for schema in (True, False, {"items": [True, False]}):
            with self.subTest(schema=schema):
                with self.assertRaises(SchemaError):
                    canonicalize_schema(schema, dialect=Dialect.DRAFT4)

    def test_public_schema_validation_uses_ecma_regex_frontend(self):
        self.assertEqual(
            canonicalize_schema({"type": "string", "pattern": r"^\cA$"}),
            {"type": "string", "pattern": r"^\cA$"},
        )
        with self.assertRaises(SchemaError):
            canonicalize_schema({"type": "string", "pattern": "["})
        with self.assertRaises(SchemaError):
            canonicalize_schema({"patternProperties": {r"\0": {}}})

    def test_valid_but_unproved_ecma_regex_reaches_proof_boundary(self):
        schema = {"type": "string", "pattern": "(?=a)"}

        self.assertEqual(canonicalize_schema(schema, dialect=Dialect.DRAFT202012), schema)
        with self.assertRaises(UnsupportedProofError) as raised:
            is_subschema({"type": "string"}, schema, dialect=Dialect.DRAFT202012)
        self.assertEqual(raised.exception.status, "unsupported")
        self.assertEqual(len(raised.exception.diagnostics), 1)
        self.assertEqual(
            raised.exception.diagnostics[0].format(),
            "rhs #/pattern: non-regular-regex: lookaround/zero-width assertions "
            "are unsupported",
        )

    def test_unsupported_proof_error_formats_all_diagnostics(self):
        with self.assertRaises(UnsupportedProofError) as raised:
            is_subschema({"$dynamicRef": "#lhs"}, {"$dynamicRef": "#rhs"})

        self.assertEqual(raised.exception.status, "unsupported")
        self.assertGreaterEqual(len(raised.exception.diagnostics), 2)
        self.assertIn(
            "lhs #/$dynamicRef",
            raised.exception.format(),
        )
        self.assertIn(
            "rhs #/$dynamicRef",
            raised.exception.format(),
        )

    def test_proof_result_repr_summarizes_large_payloads(self):
        proof = ProofResult.false(["x"] * 1000)

        representation = repr(proof)

        self.assertIn("status='proved_false'", representation)
        self.assertIn("witness_type=list", representation)
        self.assertNotIn("'x', 'x', 'x'", representation)

    def test_public_error_hierarchy(self):
        self.assertTrue(issubclass(UnsupportedProofError, SubschemaError))
        self.assertTrue(issubclass(UnsupportedKeywordError, UnsupportedProofError))
        with self.assertRaises(SubschemaError):
            is_subschema({"$ref": "#"}, {"type": "object"})

    def test_public_api_rejects_non_json_numbers(self):
        invalid_schemas = (
            {"const": nan},
            {"enum": [inf]},
            {"properties": {"value": {"const": -inf}}},
        )

        for schema in invalid_schemas:
            with self.subTest(schema=schema):
                with self.assertRaises(ValueError):
                    canonicalize_schema(schema)
                with self.assertRaises(ValueError):
                    is_subschema(schema, True)
                with self.assertRaises(ValueError):
                    is_equivalent(True, schema)
                with self.assertRaises(ValueError):
                    meet_schemas(schema, True)
                with self.assertRaises(ValueError):
                    join_schemas(True, schema)

    def test_cli_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            lhs = Path(tmp) / "lhs.json"
            rhs = Path(tmp) / "rhs.json"
            lhs.write_text(json.dumps({"type": "integer"}))
            rhs.write_text(json.dumps({"type": "number"}))

            completed = subprocess.run(
                [sys.executable, "-m", "subschema.cli", str(lhs), str(rhs)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("LHS <: RHS True", completed.stdout)

    def test_cli_help_names_subschema(self):
        completed = subprocess.run(
            [sys.executable, "-m", "subschema.cli", "--help"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("subschema tool", completed.stdout)
        self.assertNotIn("ssonsub" "schema", completed.stdout)

    def test_cli_rejects_non_json_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            lhs = Path(tmp) / "lhs.json"
            rhs = Path(tmp) / "rhs.json"
            lhs.write_text('{"const": NaN}')
            rhs.write_text(json.dumps({"type": "number"}))

            completed = subprocess.run(
                [sys.executable, "-m", "subschema.cli", str(lhs), str(rhs)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("NaN is not valid JSON", completed.stderr)

    def test_strict_json_loader_rejects_duplicate_object_keys(self):
        with self.assertRaisesRegex(ValueError, "duplicate object key 'type'"):
            strict_json_loads('{"type": "string", "type": "number"}')

    def test_cli_rejects_duplicate_object_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            lhs = Path(tmp) / "lhs.json"
            rhs = Path(tmp) / "rhs.json"
            lhs.write_text('{"type": "integer", "type": "number"}')
            rhs.write_text(json.dumps({"type": "number"}))

            completed = subprocess.run(
                [sys.executable, "-m", "subschema.cli", str(lhs), str(rhs)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("duplicate object key 'type'", completed.stderr)

    def test_cli_reports_unsupported_diagnostic_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            lhs = Path(tmp) / "lhs.json"
            rhs = Path(tmp) / "rhs.json"
            lhs.write_text(json.dumps({"type": "string"}))
            rhs.write_text(json.dumps({"type": "string", "pattern": "(?=a)"}))

            completed = subprocess.run(
                [sys.executable, "-m", "subschema.cli", str(lhs), str(rhs)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unsupported proof: rhs #/pattern", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_cli_reports_multiple_unsupported_diagnostic_pointers(self):
        with tempfile.TemporaryDirectory() as tmp:
            lhs = Path(tmp) / "lhs.json"
            rhs = Path(tmp) / "rhs.json"
            lhs.write_text(json.dumps({"$dynamicRef": "#lhs"}))
            rhs.write_text(json.dumps({"$dynamicRef": "#rhs"}))

            completed = subprocess.run(
                [sys.executable, "-m", "subschema.cli", str(lhs), str(rhs)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("diagnostics:", completed.stderr)
        self.assertIn("lhs #/$dynamicRef", completed.stderr)
        self.assertIn("rhs #/$dynamicRef", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_cli_rejects_invalid_budget_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            lhs = Path(tmp) / "lhs.json"
            rhs = Path(tmp) / "rhs.json"
            lhs.write_text(json.dumps({"type": "integer"}))
            rhs.write_text(json.dumps({"type": "number"}))

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "subschema.cli",
                    "--max-work",
                    "-2",
                    "--timeout-ms",
                    "1000",
                    str(lhs),
                    str(rhs),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("value must be -1 or greater", completed.stderr)

    def test_cli_rejects_budget_arguments_without_endeavor(self):
        with tempfile.TemporaryDirectory() as tmp:
            lhs = Path(tmp) / "lhs.json"
            rhs = Path(tmp) / "rhs.json"
            lhs.write_text(json.dumps({"type": "integer"}))
            rhs.write_text(json.dumps({"type": "number"}))

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "subschema.cli",
                    "--max-work",
                    "1",
                    str(lhs),
                    str(rhs),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("--max-work and --timeout-ms require --endeavor", completed.stderr)

    def test_public_api_rejects_invalid_proof_options_type(self):
        with self.assertRaises(TypeError):
            is_subschema({"type": "string"}, {"type": "string"}, proof_options={})
        with self.assertRaises(TypeError):
            meet_schemas({"type": "string"}, {"type": "string"}, proof_options="endeavor")
        with self.assertRaises(TypeError):
            join_schemas({"type": "string"}, {"type": "string"}, proof_options=[])
        with self.assertRaises(TypeError):
            is_equivalent({"type": "string"}, {"type": "string"}, proof_options=object())

    def test_public_api_rejects_mixed_proof_option_styles(self):
        proof_options = ProofOptions()

        with self.assertRaises(ValueError):
            is_subschema(
                {"type": "string"},
                {"type": "string"},
                proof_options=proof_options,
                max_work=1,
            )

    def test_public_api_rejects_budget_without_endeavor(self):
        with self.assertRaises(ValueError):
            is_subschema({"type": "integer"}, {"type": "number"}, max_work=1)
        with self.assertRaises(ValueError):
            is_equivalent({"type": "integer"}, {"type": "number"}, timeout_ms=1)

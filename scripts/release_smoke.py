from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass
from email import message_from_string
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_ARCHIVE_PREFIXES = (
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    "__pycache__/",
    "build/",
    "docs/",
    "dist/",
    "DCO1.1.txt",
    "jsonsubschema/",
    "PLAN.md",
    "test/",
    "tests/",
)
FORBIDDEN_DEPENDENCIES = frozenset({"jsonref", "portion"})
EXPECTED_PROJECT_URLS = {
    "Homepage": "https://github.com/ArakawaHenri/subschema",
    "Repository": "https://github.com/ArakawaHenri/subschema",
}


@dataclass(frozen=True)
class ProjectMetadata:
    name: str
    version: str
    requires_python: str
    license_expression: str
    project_urls: dict[str, str]
    forbidden_dependencies: frozenset[str] = FORBIDDEN_DEPENDENCIES


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    project = load_project_metadata(REPO_ROOT / "pyproject.toml")
    failures: list[str] = []

    wheel, sdist = find_release_artifacts(args.dist_dir, project)
    if wheel is None:
        failures.append(
            f"missing wheel for {project.name} {project.version} in {args.dist_dir}"
        )
    else:
        failures.extend(inspect_wheel(wheel, project))

    if sdist is None:
        failures.append(
            f"missing sdist for {project.name} {project.version} in {args.dist_dir}"
        )
    else:
        failures.extend(inspect_sdist(sdist))

    if not args.skip_cli:
        failures.extend(run_cli_smoke())
    if wheel is not None and not args.skip_isolated_install:
        failures.extend(run_isolated_wheel_smoke(wheel))

    if failures:
        print("release smoke failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(f"release smoke passed for {project.name} {project.version}")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect built subschema artifacts before publishing.",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=REPO_ROOT / "dist",
        help="Directory containing built wheel and sdist artifacts.",
    )
    parser.add_argument(
        "--skip-cli",
        action="store_true",
        help="Skip the local python -m subschema.cli smoke check.",
    )
    parser.add_argument(
        "--skip-isolated-install",
        action="store_true",
        help="Skip isolated wheel install/import smoke.",
    )
    return parser.parse_args(argv)


def load_project_metadata(pyproject_path: Path) -> ProjectMetadata:
    data = tomllib.loads(pyproject_path.read_text())
    project = data["project"]
    return ProjectMetadata(
        name=project["name"],
        version=project["version"],
        requires_python=project["requires-python"],
        license_expression=project["license"],
        project_urls=dict(project.get("urls", {})),
    )


def find_release_artifacts(
    dist_dir: Path, project: ProjectMetadata
) -> tuple[Path | None, Path | None]:
    normalized_name = project.name.replace("-", "_")
    wheel = _single_match(
        dist_dir.glob(f"{normalized_name}-{project.version}-*.whl")
    )
    sdist = _single_match(dist_dir.glob(f"{project.name}-{project.version}.tar.gz"))
    return wheel, sdist


def inspect_wheel(wheel_path: Path, project: ProjectMetadata) -> list[str]:
    failures: list[str] = []
    with zipfile.ZipFile(wheel_path) as archive:
        names = archive.namelist()
        metadata_name = _single_name(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        if metadata_name is None:
            return [f"{wheel_path.name}: missing METADATA"]

        metadata = message_from_string(archive.read(metadata_name).decode())
        if metadata.get("Name") != project.name:
            failures.append(
                f"{wheel_path.name}: Name is {metadata.get('Name')!r}, "
                f"expected {project.name!r}"
            )
        if metadata.get("Version") != project.version:
            failures.append(
                f"{wheel_path.name}: Version is {metadata.get('Version')!r}, "
                f"expected {project.version!r}"
            )
        if metadata.get("Requires-Python") != project.requires_python:
            failures.append(
                f"{wheel_path.name}: Requires-Python is "
                f"{metadata.get('Requires-Python')!r}, "
                f"expected {project.requires_python!r}"
            )
        if metadata.get("License-Expression") != project.license_expression:
            failures.append(
                f"{wheel_path.name}: License-Expression is "
                f"{metadata.get('License-Expression')!r}, "
                f"expected {project.license_expression!r}"
            )
        if "LICENSE" not in (metadata.get_all("License-File") or []):
            failures.append(f"{wheel_path.name}: missing LICENSE license file")
        metadata_urls = _project_urls(metadata.get_all("Project-URL") or [])
        for label, expected_url in project.project_urls.items():
            actual_url = metadata_urls.get(label)
            if actual_url != expected_url:
                failures.append(
                    f"{wheel_path.name}: Project-URL {label!r} is "
                    f"{actual_url!r}, expected {expected_url!r}"
                )
        for label, expected_url in EXPECTED_PROJECT_URLS.items():
            actual_url = metadata_urls.get(label)
            if actual_url != expected_url:
                failures.append(
                    f"{wheel_path.name}: required Project-URL {label!r} is "
                    f"{actual_url!r}, expected {expected_url!r}"
                )
        forbidden_dependencies = sorted(
            requirement
            for requirement in (metadata.get_all("Requires-Dist") or [])
            if _requirement_name(requirement) in project.forbidden_dependencies
        )
        failures.extend(
            f"{wheel_path.name}: forbidden dependency {requirement}"
            for requirement in forbidden_dependencies
        )

        failures.extend(_required_archive_entries(wheel_path.name, names))
        failures.extend(_forbidden_archive_entries(wheel_path.name, names))
    return failures


def inspect_sdist(sdist_path: Path) -> list[str]:
    with tarfile.open(sdist_path) as archive:
        names = [_strip_sdist_root(member.name) for member in archive.getmembers()]

    failures = _required_archive_entries(sdist_path.name, names)
    failures.extend(_forbidden_archive_entries(sdist_path.name, names))
    if "pyproject.toml" not in names:
        failures.append(f"{sdist_path.name}: missing pyproject.toml")
    if "README.md" not in names:
        failures.append(f"{sdist_path.name}: missing README.md")
    if "LICENSE" not in names:
        failures.append(f"{sdist_path.name}: missing LICENSE")
    return failures


def run_cli_smoke() -> list[str]:
    completed = subprocess.run(
        [sys.executable, "-m", "subschema.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if completed.returncode != 0:
        return [f"CLI help failed: {completed.stderr or completed.stdout}"]
    if "subschema tool" not in completed.stdout:
        return ["CLI help did not identify the subschema tool"]
    return []


def run_isolated_wheel_smoke(wheel_path: Path) -> list[str]:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="subschema-release-smoke-") as tmp:
        venv_dir = Path(tmp) / "venv"
        create_venv = subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(venv_dir)],
            check=False,
            capture_output=True,
            text=True,
        )
        if create_venv.returncode != 0:
            return [
                "isolated venv creation failed: "
                f"{create_venv.stderr or create_venv.stdout}"
            ]
        python = _venv_python(venv_dir)
        install = subprocess.run(
            ["uv", "pip", "install", "--python", str(python), str(wheel_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if install.returncode != 0:
            return [
                "isolated wheel install failed: "
                f"{install.stderr or install.stdout}"
            ]

        import_smoke = subprocess.run(
            [
                str(python),
                "-c",
                (
                    "from subschema import is_subschema; "
                    "assert is_subschema({'type': 'integer'}, {'type': 'number'}); "
                    "import importlib.util; "
                    "assert importlib.util.find_spec('jsonsubschema') is None"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if import_smoke.returncode != 0:
            failures.append(
                "isolated import smoke failed: "
                f"{import_smoke.stderr or import_smoke.stdout}"
            )

        cli_smoke = subprocess.run(
            [str(python), "-m", "subschema.cli", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        if cli_smoke.returncode != 0:
            failures.append(
                "isolated CLI smoke failed: "
                f"{cli_smoke.stderr or cli_smoke.stdout}"
            )
        elif "subschema tool" not in cli_smoke.stdout:
            failures.append("isolated CLI help did not identify the subschema tool")
    return failures


def _single_match(matches: object) -> Path | None:
    paths = sorted(matches)
    return paths[0] if len(paths) == 1 else None


def _single_name(names: object) -> str | None:
    name_list = sorted(names)
    return name_list[0] if len(name_list) == 1 else None


def _required_archive_entries(archive_name: str, names: list[str]) -> list[str]:
    failures: list[str] = []
    if (
        "subschema/__init__.py" not in names
        and "src/subschema/__init__.py" not in names
    ):
        failures.append(f"{archive_name}: missing subschema package")
    if "subschema/py.typed" not in names and "src/subschema/py.typed" not in names:
        failures.append(f"{archive_name}: missing py.typed")
    return failures


def _forbidden_archive_entries(archive_name: str, names: list[str]) -> list[str]:
    return [
        f"{archive_name}: contains forbidden path {name}"
        for name in names
        if name.startswith(FORBIDDEN_ARCHIVE_PREFIXES)
    ]


def _strip_sdist_root(name: str) -> str:
    parts = name.split("/", 1)
    return parts[1] if len(parts) == 2 else name


def _project_urls(project_url_values: list[str]) -> dict[str, str]:
    urls: dict[str, str] = {}
    for value in project_url_values:
        label, separator, url = value.partition(",")
        if separator:
            urls[label.strip()] = url.strip()
    return urls


def _requirement_name(requirement: str) -> str:
    name_chars = []
    for character in requirement:
        if character.isalnum() or character in {"-", "_", "."}:
            name_chars.append(character)
            continue
        break
    return "".join(name_chars).lower().replace("_", "-")


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


if __name__ == "__main__":
    raise SystemExit(main())

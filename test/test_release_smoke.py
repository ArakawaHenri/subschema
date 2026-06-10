from __future__ import annotations

import importlib.util
import io
import sys
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace


def _load_release_smoke() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "scripts/release_smoke.py"
    spec = importlib.util.spec_from_file_location("release_smoke", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_release_smoke_accepts_clean_wheel(tmp_path) -> None:
    release_smoke = _load_release_smoke()
    project = _project(release_smoke)
    wheel = _write_wheel(tmp_path, project)

    assert release_smoke.inspect_wheel(wheel, project) == []


def test_release_smoke_rejects_old_package_paths_in_wheel(tmp_path) -> None:
    release_smoke = _load_release_smoke()
    project = _project(release_smoke)
    wheel = _write_wheel(
        tmp_path,
        project,
        extra_entries={"jsonsubschema/__init__.py": ""},
    )

    failures = release_smoke.inspect_wheel(wheel, project)

    assert any("jsonsubschema/__init__.py" in failure for failure in failures)


def test_release_smoke_rejects_forbidden_dependencies(tmp_path) -> None:
    release_smoke = _load_release_smoke()
    project = _project(release_smoke)
    wheel = _write_wheel(
        tmp_path,
        project,
        extra_requires=("jsonref>=1", "portion"),
    )

    failures = release_smoke.inspect_wheel(wheel, project)

    assert any("jsonref" in failure for failure in failures)
    assert any("portion" in failure for failure in failures)


def test_release_smoke_rejects_missing_project_urls(tmp_path) -> None:
    release_smoke = _load_release_smoke()
    project = _project(release_smoke)
    wheel = _write_wheel(tmp_path, project, project_urls={})

    failures = release_smoke.inspect_wheel(wheel, project)

    assert any("Project-URL 'Homepage'" in failure for failure in failures)
    assert any("Project-URL 'Repository'" in failure for failure in failures)


def test_release_smoke_accepts_clean_sdist(tmp_path) -> None:
    release_smoke = _load_release_smoke()
    project = _project(release_smoke)
    sdist = _write_sdist(tmp_path, project)

    assert release_smoke.inspect_sdist(sdist) == []


def test_release_smoke_rejects_tests_in_sdist(tmp_path) -> None:
    release_smoke = _load_release_smoke()
    project = _project(release_smoke)
    sdist = _write_sdist(tmp_path, project, extra_entries={"test/test_api.py": ""})

    failures = release_smoke.inspect_sdist(sdist)

    assert any("test/test_api.py" in failure for failure in failures)


def test_release_smoke_finds_matching_artifacts(tmp_path) -> None:
    release_smoke = _load_release_smoke()
    project = _project(release_smoke)
    wheel = _write_wheel(tmp_path, project)
    sdist = _write_sdist(tmp_path, project)

    assert release_smoke.find_release_artifacts(tmp_path, project) == (wheel, sdist)


def test_release_smoke_runs_isolated_wheel_smoke(monkeypatch, tmp_path) -> None:
    release_smoke = _load_release_smoke()
    wheel = tmp_path / "subschema-1.2.3-py3-none-any.whl"
    wheel.write_text("")
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append([str(part) for part in command])
        return SimpleNamespace(returncode=0, stdout="subschema tool", stderr="")

    monkeypatch.setattr(release_smoke.subprocess, "run", fake_run)

    assert release_smoke.run_isolated_wheel_smoke(wheel) == []
    assert commands[0][:3] == ["uv", "venv", "--python"]
    assert commands[1][:4] == ["uv", "pip", "install", "--python"]
    assert commands[2][1] == "-c"
    assert "find_spec('jsonsubschema')" in commands[2][2]
    assert commands[3][-3:] == ["-m", "subschema.cli", "--help"]


def _project(release_smoke):
    return release_smoke.ProjectMetadata(
        name="subschema",
        version="1.2.3",
        requires_python=">=3.12",
        license_expression="Apache-2.0",
        project_urls={
            "Homepage": "https://github.com/ArakawaHenri/subschema",
            "Repository": "https://github.com/ArakawaHenri/subschema",
        },
    )


def _write_wheel(
    tmp_path: Path,
    project,
    *,
    extra_entries: dict[str, str] | None = None,
    extra_requires: tuple[str, ...] = (),
    project_urls: dict[str, str] | None = None,
) -> Path:
    wheel = tmp_path / f"subschema-{project.version}-py3-none-any.whl"
    urls = project.project_urls if project_urls is None else project_urls
    metadata = "\n".join(
        (
            "Metadata-Version: 2.4",
            f"Name: {project.name}",
            f"Version: {project.version}",
            f"Requires-Python: {project.requires_python}",
            f"License-Expression: {project.license_expression}",
            "License-File: LICENSE",
            *(f"Project-URL: {label}, {url}" for label, url in urls.items()),
            "Requires-Dist: greenery>=4.0.0",
            "Requires-Dist: jsonschema",
            "Requires-Dist: jsonschema-rs>=0.46.5",
            "Requires-Dist: referencing",
            "Requires-Dist: z3-solver",
            *(f"Requires-Dist: {requirement}" for requirement in extra_requires),
            "",
        )
    )
    entries = {
        "subschema/__init__.py": "",
        "subschema/py.typed": "",
        f"subschema-{project.version}.dist-info/METADATA": metadata,
    }
    entries.update(extra_entries or {})
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return wheel


def _write_sdist(
    tmp_path: Path,
    project,
    *,
    extra_entries: dict[str, str] | None = None,
) -> Path:
    root = f"subschema-{project.version}"
    sdist = tmp_path / f"{root}.tar.gz"
    entries = {
        f"{root}/pyproject.toml": "",
        f"{root}/README.md": "",
        f"{root}/LICENSE": "",
        f"{root}/src/subschema/__init__.py": "",
        f"{root}/src/subschema/py.typed": "",
    }
    for name, content in (extra_entries or {}).items():
        entries[f"{root}/{name}"] = content
    with tarfile.open(sdist, "w:gz") as archive:
        for name, content in entries.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return sdist

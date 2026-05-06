from __future__ import annotations

import ast
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"


def _python_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _import_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _import_references(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    refs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            refs.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            refs.append(node.module)
            refs.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return refs


class ArchitectureBoundaryTest(unittest.TestCase):
    def test_legacy_top_level_directories_are_removed(self) -> None:
        legacy_dirs = (
            "api",
            "agents",
            "auth",
            "db",
            "graph",
            "llm",
            "mcp",
            "memory",
            "practice",
            "qa_runtime",
            "retrieval",
            "schemas",
            "tools",
            "workflow",
        )

        offenders = [name for name in legacy_dirs if (BACKEND_ROOT / name).exists()]
        self.assertEqual(offenders, [])

    def test_deprecated_app_facade_files_are_removed(self) -> None:
        deprecated_paths = (
            APP_ROOT / "infrastructure" / "db" / "repositories" / "compat.py",
            APP_ROOT / "infrastructure" / "llm" / "selection.py",
            APP_ROOT / "infrastructure" / "tools",
            APP_ROOT / "interfaces" / "mcp",
            APP_ROOT / "services" / "retrieval" / "store.py",
            APP_ROOT / "interfaces" / "auth" / "email_sender.py",
            APP_ROOT / "interfaces" / "auth" / "security.py",
            APP_ROOT / "interfaces" / "auth" / "verification.py",
        )

        offenders = [str(path.relative_to(BACKEND_ROOT)) for path in deprecated_paths if path.exists()]
        self.assertEqual(offenders, [])

    def test_application_layer_has_no_http_or_interface_imports(self) -> None:
        offenders: list[str] = []
        for path in _python_files(APP_ROOT / "application"):
            imports = _import_names(path)
            bad_imports = [
                name
                for name in imports
                if name == "fastapi"
                or name.startswith("fastapi.")
                or name == "app.interfaces"
                or name.startswith("app.interfaces.")
            ]
            if bad_imports:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)} -> {', '.join(sorted(set(bad_imports)))}")

        self.assertEqual(offenders, [])

    def test_infrastructure_layer_has_no_upward_imports(self) -> None:
        disallowed_prefixes = (
            "app.interfaces",
            "app.application",
            "app.domains",
            "app.services",
        )
        offenders: list[str] = []

        for path in _python_files(APP_ROOT / "infrastructure"):
            imports = _import_names(path)
            bad_imports = [
                name
                for name in imports
                if name in disallowed_prefixes
                or any(name.startswith(f"{prefix}.") for prefix in disallowed_prefixes)
            ]
            if bad_imports:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)} -> {', '.join(sorted(set(bad_imports)))}")

        self.assertEqual(offenders, [])

    def test_shared_layer_has_no_runtime_layer_imports(self) -> None:
        disallowed_prefixes = (
            "app.interfaces",
            "app.application",
            "app.orchestration",
            "app.domains",
            "app.services",
            "app.infrastructure",
        )
        offenders: list[str] = []

        for path in _python_files(APP_ROOT / "shared"):
            imports = _import_names(path)
            bad_imports = [
                name
                for name in imports
                if name in disallowed_prefixes
                or any(name.startswith(f"{prefix}.") for prefix in disallowed_prefixes)
            ]
            if bad_imports:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)} -> {', '.join(sorted(set(bad_imports)))}")

        self.assertEqual(offenders, [])

    def test_domain_layer_does_not_depend_on_orchestration(self) -> None:
        offenders: list[str] = []
        for path in _python_files(APP_ROOT / "domains"):
            imports = _import_names(path)
            bad_imports = [
                name
                for name in imports
                if name == "app.orchestration" or name.startswith("app.orchestration.")
            ]
            if bad_imports:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)} -> {', '.join(sorted(set(bad_imports)))}")

        self.assertEqual(offenders, [])

    def test_non_compatibility_tests_do_not_import_legacy_top_level_modules(self) -> None:
        legacy_roots = (
            "api",
            "agents",
            "auth",
            "db",
            "graph",
            "llm",
            "mcp",
            "memory",
            "practice",
            "qa_runtime",
            "retrieval",
            "schemas",
            "tools",
            "workflow",
        )
        offenders: list[str] = []
        for path in _python_files(BACKEND_ROOT / "tests"):
            imports = _import_names(path)
            bad_imports = [
                name
                for name in imports
                if name in legacy_roots
                or any(name.startswith(f"{root}.") for root in legacy_roots)
            ]
            if bad_imports:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)} -> {', '.join(sorted(set(bad_imports)))}")

        self.assertEqual(offenders, [])

    def test_app_and_scripts_do_not_import_legacy_top_level_modules(self) -> None:
        legacy_roots = (
            "api",
            "agents",
            "auth",
            "db",
            "graph",
            "llm",
            "mcp",
            "memory",
            "practice",
            "qa_runtime",
            "retrieval",
            "schemas",
            "tools",
            "workflow",
        )
        offenders: list[str] = []
        roots = [APP_ROOT, BACKEND_ROOT / "scripts"]

        for root in roots:
            for path in _python_files(root):
                imports = _import_names(path)
                bad_imports = [
                    name
                    for name in imports
                    if name in legacy_roots
                    or any(name.startswith(f"{root_name}.") for root_name in legacy_roots)
                ]
                if bad_imports:
                    offenders.append(f"{path.relative_to(BACKEND_ROOT)} -> {', '.join(sorted(set(bad_imports)))}")

        self.assertEqual(offenders, [])

    def test_repo_main_path_does_not_import_deprecated_app_facades(self) -> None:
        deprecated_facades = {
            "app.infrastructure.db.repositories",
            "app.infrastructure.llm.selection",
            "app.infrastructure.tools",
            "app.infrastructure.tools.runtime",
            "app.interfaces.mcp",
            "app.services.retrieval.store",
        }
        offenders: list[str] = []
        roots = [APP_ROOT, BACKEND_ROOT / "scripts", BACKEND_ROOT / "tests"]

        for root in roots:
            for path in _python_files(root):
                refs = _import_references(path)
                bad_imports = sorted({ref for ref in refs if ref in deprecated_facades})
                if bad_imports:
                    offenders.append(f"{path.relative_to(BACKEND_ROOT)} -> {', '.join(bad_imports)}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()

"""Execute generated test suites for A-06 validation.

Runs each part's suites in a throwaway copy of the part dir, against cached
per-stack environments:
- Python backends: uv-managed venv per (python version, requirements.txt hash).
- Node backend / React frontend: node_modules per package.json hash (the
  playbooks fix package.json verbatim, so each stack installs exactly once).

Raises RunnerUnavailable when execution simply isn't possible here (missing
runtime, install/network failure) so the caller can skip validation instead of
failing the question.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "fs_gen"
ENV_SETUP_TIMEOUT = 900
SUITE_TIMEOUT = 420
OUTPUT_TAIL = 20000  # jest failure output with DOM dumps is huge; the fixer needs the evidence

# Old HackerEarth pins need old interpreters (Flask 1.1/Django 3.x break on 3.12).
_PY_FOR_KIND = {"fastapi": "3.11", "flask": "3.8", "django": "3.8"}


class RunnerUnavailable(Exception):
    """Execution not possible in this environment — skip validation, don't fail."""


@dataclass
class SuiteResult:
    suite: str  # e.g. "backend/test.py", "frontend/main.test.js"
    ok: bool
    passed: int
    failed: int
    output: str


def _backend_kind(stack: str) -> str:
    for kind in ("fastapi", "flask", "django", "nodejs"):
        if kind in stack:
            return kind
    raise ValueError(f"unknown stack: {stack}")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _sh(cmd: list[str], cwd: Path, timeout: int, env: dict | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
            env={**os.environ, **(env or {})},
        )
    except FileNotFoundError as exc:
        raise RunnerUnavailable(f"missing runtime: {cmd[0]}") from exc


def _tail(r: subprocess.CompletedProcess) -> str:
    """Head + tail of the run output — parse/import errors print their cause at the TOP."""
    out = r.stdout + "\n" + r.stderr
    if len(out) <= OUTPUT_TAIL:
        return out
    head = OUTPUT_TAIL // 3
    return out[:head] + "\n[... output trimmed ...]\n" + out[-(OUTPUT_TAIL - head):]


# ── Environment caches ──────────────────────────────────────────────────────

def ensure_python_env(requirements: Path, py: str) -> Path:
    """Return the venv python for these pinned requirements, creating it once."""
    env_dir = CACHE_DIR / "venvs" / f"py{py}-{_hash(requirements.read_text())}"
    python = env_dir / "bin" / "python"
    if python.exists():
        return python
    env_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = _sh(["uv", "venv", "--python", py, str(env_dir)], cwd=env_dir.parent, timeout=ENV_SETUP_TIMEOUT)
        if r.returncode == 0:
            r = _sh(["uv", "pip", "install", "--python", str(python), "-r", str(requirements)],
                    cwd=requirements.parent, timeout=ENV_SETUP_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(env_dir, ignore_errors=True)
        raise RunnerUnavailable(f"venv setup timed out for python {py}") from exc
    if r.returncode != 0:
        shutil.rmtree(env_dir, ignore_errors=True)
        raise RunnerUnavailable(f"pip install failed: {_tail(r)[-800:]}")
    return python


def ensure_node_modules(package_json: Path) -> Path:
    """Return a cached node_modules dir for this package.json, installing once."""
    cache = CACHE_DIR / "node" / _hash(package_json.read_text())
    node_modules = cache / "node_modules"
    if node_modules.exists():
        return node_modules
    cache.mkdir(parents=True, exist_ok=True)
    shutil.copy(package_json, cache / "package.json")
    try:
        r = _sh(["npm", "install", "--prefer-offline", "--no-audit", "--no-fund"],
                cwd=cache, timeout=ENV_SETUP_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(node_modules, ignore_errors=True)
        raise RunnerUnavailable("npm install timed out") from exc
    if r.returncode != 0 or not node_modules.exists():
        shutil.rmtree(node_modules, ignore_errors=True)
        raise RunnerUnavailable(f"npm install failed: {_tail(r)[-800:]}")
    return node_modules


# ── Output parsers ──────────────────────────────────────────────────────────

def _parse_pytest(out: str) -> tuple[int, int]:
    passed = sum(int(n) for n in re.findall(r"(\d+) passed", out))
    failed = sum(int(n) for n in re.findall(r"(\d+) (?:failed|error)", out))
    return passed, failed


def _parse_jest(out: str) -> tuple[int, int]:
    m = re.search(r"Tests:\s+(?:(\d+) failed, )?(?:(\d+) skipped, )?(?:(\d+) passed, )?(\d+) total", out)
    if not m:
        return 0, 0
    failed = int(m.group(1) or 0)
    passed = int(m.group(3) or 0)
    return passed, failed


def _parse_unittest(out: str) -> tuple[int, int]:
    ran = int(m.group(1)) if (m := re.search(r"Ran (\d+) tests?", out)) else 0
    failed = 0
    if m := re.search(r"FAILED \(([^)]*)\)", out):
        failed = sum(int(n) for n in re.findall(r"(?:failures|errors)=(\d+)", m.group(1)))
    return ran - failed, failed


# ── Suite execution ─────────────────────────────────────────────────────────

def _django_targets(backend: Path) -> dict[str, str]:
    if (backend / "app" / "tests.py").exists():  # Easy layout
        return {"hidden": "app.tests", "sample": "app.sample_tests"}
    return {"hidden": "tests", "sample": "sample_tests"}


def _run_python_backend(kind: str, backend_src: Path, suites: list[str]) -> list[SuiteResult]:
    python = ensure_python_env(backend_src / "requirements.txt", _PY_FOR_KIND[kind])
    results = []
    run_dir = Path(tempfile.mkdtemp(prefix="fsgen-run-"))
    try:
        work = run_dir / "backend"
        shutil.copytree(backend_src, work)
        for suite in suites:
            if kind == "django":
                target = _django_targets(work)["hidden" if suite == "hidden" else "sample"]
                cmd = [str(python), "manage.py", "test", target, "--noinput"]
                name = f"backend/{target}"
            else:
                fname = "test.py" if suite == "hidden" else "sample_test.py"
                cmd = [str(python), "-m", "pytest", fname, "-q", "-p", "no:cacheprovider"]
                name = f"backend/{fname}"
            r = _sh(cmd, cwd=work, timeout=SUITE_TIMEOUT)
            parse = _parse_unittest if kind == "django" else _parse_pytest
            passed, failed = parse(r.stdout + r.stderr)
            results.append(SuiteResult(name, r.returncode == 0, passed, failed, _tail(r)))
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
    return results


def _run_jest(part_src: Path, part_name: str, files: list[str], extra_args: list[str],
              env: dict | None = None) -> list[SuiteResult]:
    node_modules = ensure_node_modules(part_src / "package.json")
    results = []
    run_dir = Path(tempfile.mkdtemp(prefix="fsgen-run-"))
    try:
        work = run_dir / part_name
        shutil.copytree(part_src, work)
        (work / "node_modules").symlink_to(node_modules)
        jest = str(node_modules / ".bin" / "jest")
        for f in files:
            r = _sh([jest, f, "--runInBand", "--forceExit", *extra_args],
                    cwd=work, timeout=SUITE_TIMEOUT, env=env)
            passed, failed = _parse_jest(r.stdout + r.stderr)
            results.append(SuiteResult(f"{part_name}/{f}", r.returncode == 0, passed, failed, _tail(r)))
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
    return results


def run_part_suites(stack: str, part_dir: str, suites: list[str] | None = None) -> list[SuiteResult]:
    """Run test suites for one tree (skeleton/ or solution/). suites ⊆ {hidden, sample}."""
    suites = suites or ["hidden", "sample"]
    part = Path(part_dir).resolve()
    kind = _backend_kind(stack)
    backend = part / "backend" if (part / "backend").exists() else part

    if kind == "nodejs":
        files = [{"hidden": "tests/index.test.js", "sample": "tests/sample.test.js"}[s] for s in suites]
        results = _run_jest(backend, "backend", files, [], env={"port": "0", "PORT": "0"})
    else:
        results = _run_python_backend(kind, backend, suites)

    if (part / "frontend").exists():
        files = [{"hidden": "main.test.js", "sample": "sample.test.js"}[s] for s in suites]
        results += _run_jest(part / "frontend", "frontend", files, ["--testTimeout=10000"], env={"CI": "true"})
    return results

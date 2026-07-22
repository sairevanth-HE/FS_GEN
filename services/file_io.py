"""Sync file I/O utilities for agent tool handlers."""

from __future__ import annotations

from pathlib import Path


def write_files(files: dict, output_dir: str) -> dict:
    """Write multiple files to disk under output_dir."""
    base = Path(output_dir)
    for rel_path, content in files.items():
        dest = base / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return {"files_written": len(files), "output_dir": output_dir}


def read_file(path: str) -> str:
    """Read and return the content of a single file."""
    return Path(path).read_text(encoding="utf-8")


def read_files(paths: list) -> dict:
    """Read multiple files at once. Returns {path: content}. Missing files get an
    '<error: ...>' placeholder rather than raising, so one bad path doesn't lose the
    whole batch."""
    out = {}
    for p in paths:
        try:
            out[p] = Path(p).read_text(encoding="utf-8")
        except OSError as exc:
            out[p] = f"<error reading {p}: {exc}>"
    return out


def list_files(directory: str) -> list:
    """Return sorted list of relative file paths under directory (recursive)."""
    base = Path(directory)
    if not base.exists():
        return []
    return sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())


def diff_file_trees(dir1: str, dir2: str) -> dict:
    """Compare two directory trees, returns parity_ok and diff lists."""
    files1 = set(list_files(dir1))
    files2 = set(list_files(dir2))
    return {
        "only_in_dir1": sorted(files1 - files2),
        "only_in_dir2": sorted(files2 - files1),
        "in_both": sorted(files1 & files2),
        "parity_ok": files1 == files2,
    }

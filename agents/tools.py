"""
Defines:
  - All tool schemas (SCHEMA_* dicts)
  - Per-agent TOOL_DEFS lists and HANDLERS dicts

GENERATED_DIR is relative to this file's grandparent (project root).
"""

from __future__ import annotations

from pathlib import Path

from services import file_io

# Generated output root — always FS_GEN/generated/
GENERATED_DIR = Path(__file__).parent.parent / "generated"

# ── Individual tool schemas ─────────────────────────────────────────────────

SCHEMA_READ_FILE = {
    "name": "read_file",
    "description": "Read a file from disk.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}

SCHEMA_READ_FILES = {
    "name": "read_files",
    "description": "Read multiple files from disk in one call. Prefer this over read_file when you need more than one file — it saves tool-loop iterations.",
    "input_schema": {
        "type": "object",
        "properties": {
            "paths": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["paths"],
    },
}

SCHEMA_WRITE_FILES = {
    "name": "write_files",
    "description": "Write multiple files to disk. `files` maps relative path → full file content.",
    "input_schema": {
        "type": "object",
        "properties": {
            "files": {"type": "object", "additionalProperties": {"type": "string"}},
            "output_dir": {"type": "string"},
        },
        "required": ["files", "output_dir"],
    },
}

SCHEMA_LIST_FILES = {
    "name": "list_files",
    "description": "List all files under a directory (recursive).",
    "input_schema": {
        "type": "object",
        "properties": {"directory": {"type": "string"}},
        "required": ["directory"],
    },
}

SCHEMA_DIFF_FILE_TREES = {
    "name": "diff_file_trees",
    "description": "Compare two directory trees. Returns files only in each and parity_ok flag.",
    "input_schema": {
        "type": "object",
        "properties": {
            "dir1": {"type": "string", "description": "First directory (skeleton_dir)"},
            "dir2": {"type": "string", "description": "Second directory (solution_dir)"},
        },
        "required": ["dir1", "dir2"],
    },
}

_FILE_TOOL_DEFS = [
    SCHEMA_READ_FILE, SCHEMA_READ_FILES, SCHEMA_WRITE_FILES, SCHEMA_LIST_FILES, SCHEMA_DIFF_FILE_TREES,
]
_FILE_HANDLERS = {
    "read_file": file_io.read_file,
    "read_files": file_io.read_files,
    "write_files": file_io.write_files,
    "list_files": file_io.list_files,
    "diff_file_trees": file_io.diff_file_trees,
}

# ── Per-agent tool sets ─────────────────────────────────────────────────────

# A-01 Designer works purely in JSON — no tools.
DESIGNER_TOOL_DEFS: list = []
DESIGNER_HANDLERS: dict = {}

SKELETON_GENERATOR_TOOL_DEFS = _FILE_TOOL_DEFS
SKELETON_GENERATOR_HANDLERS = _FILE_HANDLERS

SOLUTION_GENERATOR_TOOL_DEFS = _FILE_TOOL_DEFS
SOLUTION_GENERATOR_HANDLERS = _FILE_HANDLERS

TEST_GENERATOR_TOOL_DEFS = _FILE_TOOL_DEFS
TEST_GENERATOR_HANDLERS = _FILE_HANDLERS

# A-04b Test Critic reviews, never writes.
TEST_CRITIC_TOOL_DEFS = [SCHEMA_READ_FILE, SCHEMA_READ_FILES, SCHEMA_LIST_FILES, SCHEMA_DIFF_FILE_TREES]
TEST_CRITIC_HANDLERS = {
    "read_file": file_io.read_file,
    "read_files": file_io.read_files,
    "list_files": file_io.list_files,
    "diff_file_trees": file_io.diff_file_trees,
}

PROBLEM_STATEMENT_TOOL_DEFS = [SCHEMA_READ_FILE, SCHEMA_WRITE_FILES, SCHEMA_LIST_FILES]
PROBLEM_STATEMENT_HANDLERS = {
    "read_file": file_io.read_file,
    "write_files": file_io.write_files,
    "list_files": file_io.list_files,
}

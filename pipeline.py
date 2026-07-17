"""
FS_GEN Pipeline Orchestrator (async)
Top-level entry point for the question pipeline (generator.md flow):
A-01 Designer → A-02 Skeleton → A-03 Solution → A-04 Tests →
A-06 Validator (executes suites: solution must pass, skeleton must fail; fixes until green) →
A-05 Problem Statement → ledger row in Postgres.

No Docker — suites run locally in cached per-stack envs (see services/test_runner.py).
If this machine can't execute a stack, validation is skipped with a warning.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import structlog

from agents.stack_specs import DOMAIN_SUGGESTIONS, STACKS
from agents.tools import GENERATED_DIR
from core.database import db_manager
from services import db as svc_db
from services import file_io
from services import question as svc_q

logger = structlog.getLogger(__name__)


async def _fail(question_id: str, result: dict, error: str) -> None:
    logger.error("pipeline_failed", question_id=question_id, error=error)
    result["status"] = "failed"
    result["error"] = error
    await svc_db.db_update_question_status(question_id, "failed")


async def _run_stage(question_id: str, result: dict, label: str, coro) -> dict | None:
    """Run one pipeline stage; convert any raised exception into a clean 'failed'
    status instead of crashing the whole run. Returns None if the stage failed."""
    try:
        stage_result = await coro
    except Exception as exc:
        logger.exception(f"{label}_raised", question_id=question_id)
        await _fail(question_id, result, f"{label} raised: {exc}")
        return None
    if stage_result.get("status") == "failed":
        await _fail(question_id, result, f"{label} failed: {stage_result.get('error', '')[:500]}")
        return None
    result["stages"][label] = stage_result
    return stage_result


async def run_generation_pipeline(stack: str, difficulty: str, domain: str) -> dict:
    """Generate one question end to end. Returns the pipeline result dict."""
    from agents import designer, problem_statement, skeleton_generator, solution_generator, test_generator, validator

    GENERATED_DIR.mkdir(exist_ok=True)
    question_id = svc_q.generate_question_id(stack, difficulty, GENERATED_DIR)
    output_dir = str(GENERATED_DIR / question_id)
    result: dict = {"question_id": question_id, "output_dir": output_dir, "stages": {}}

    print(f"→ {question_id}")
    ledger = await svc_db.db_list_questions()
    await svc_db.db_create_question(question_id, STACKS[stack], difficulty, domain, output_dir)

    print("→ A-01 Designer")
    design = await _run_stage(question_id, result, "A-01 Designer",
        designer.run(question_id, stack, difficulty, domain, ledger))
    if design is None:
        return result

    print("→ A-02 Skeleton Generator")
    if await _run_stage(question_id, result, "A-02 Skeleton Generator",
            skeleton_generator.run(question_id, output_dir, stack, difficulty, design)) is None:
        return result

    print("→ A-03 Solution Generator")
    if await _run_stage(question_id, result, "A-03 Solution Generator",
            solution_generator.run(question_id, output_dir, stack, difficulty, design)) is None:
        return result

    diff = file_io.diff_file_trees(f"{output_dir}/skeleton", f"{output_dir}/solution")
    if not diff["parity_ok"]:
        await _fail(question_id, result, f"skeleton/solution tree mismatch: {diff}")
        return result

    print("→ A-04 Test Generator")
    if await _run_stage(question_id, result, "A-04 Test Generator",
            test_generator.run(question_id, output_dir, stack, difficulty, design)) is None:
        return result

    diff = file_io.diff_file_trees(f"{output_dir}/skeleton", f"{output_dir}/solution")
    if not diff["parity_ok"]:
        await _fail(question_id, result, f"tree mismatch after tests: {diff}")
        return result

    print("→ A-06 Validator (executing test suites)")
    if await _run_stage(question_id, result, "A-06 Validator",
            validator.run(question_id, output_dir, stack, difficulty, design)) is None:
        return result

    diff = file_io.diff_file_trees(f"{output_dir}/skeleton", f"{output_dir}/solution")
    if not diff["parity_ok"]:
        await _fail(question_id, result, f"tree mismatch after validation fixes: {diff}")
        return result

    print("→ A-05 Problem Statement")
    if await _run_stage(question_id, result, "A-05 Problem Statement",
            problem_statement.run(question_id, output_dir, stack, difficulty, design)) is None:
        return result

    # Finalize: file manifest + ledger row (replaces generated_questions_log.md).
    manifest = (
        [{"relative_path": f"skeleton/{p}", "part": "skeleton"}
         for p in file_io.list_files(f"{output_dir}/skeleton")]
        + [{"relative_path": f"solution/{p}", "part": "solution"}
           for p in file_io.list_files(f"{output_dir}/solution")]
        + [{"relative_path": "problem_statement.md", "part": "root"}]
    )
    await svc_db.db_save_file_manifest(question_id, manifest)
    statement_text = file_io.read_file(f"{output_dir}/problem_statement.md")
    await svc_db.db_finalize_question(
        question_id=question_id,
        domain=design.get("domain", domain),
        entities=[e.get("name") for e in design.get("entities", [])],
        core_business_rule=design.get("core_business_rule", ""),
        problem_statement=statement_text,
    )

    result["status"] = "complete"
    result["files_logged"] = len(manifest)
    print(f"✓ complete — {output_dir} ({len(manifest)} files)")
    return result


def _pick(prompt: str, options: list[str], default: str | None = None) -> str:
    for i, opt in enumerate(options, 1):
        marker = "  (default)" if opt == default else ""
        print(f"  {i:>2}. {opt}{marker}")
    print()
    while True:
        hint = f" [1-{len(options)}]" + (f", Enter={default}" if default else "")
        raw = input(f"{prompt}{hint}: ").strip()
        if raw == "" and default:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw in options:
            return raw
        print(f"  Please enter a number between 1 and {len(options)}.")


def _interactive_mode() -> tuple[str, str, str]:
    print("\n" + "=" * 60)
    print("  FS_GEN Question Generator — Interactive Mode")
    print("=" * 60)

    print("\n── Tech stack ──\n")
    slugs = list(STACKS)
    display = [f"{STACKS[s]}  ({s})" for s in slugs]
    stack = slugs[display.index(_pick("Tech stack", display))]

    print("\n── Difficulty ──\n")
    difficulty = _pick("Difficulty", ["easy", "medium", "hard"], default="medium")

    domain = _ask_domain(stack)

    print(f"\n{'─' * 60}")
    print(f"  Tech Stack : {STACKS[stack]}")
    print(f"  Difficulty : {difficulty}")
    print(f"  Domain     : {domain}")
    print(f"{'─' * 60}")
    confirm = input("\n  Start generation? [Y/n]: ").strip().lower()
    if confirm == "n":
        print("  Aborted.")
        sys.exit(0)

    return stack, difficulty, domain


def _ask_domain(stack: str) -> str:
    """generator.md: never silently assume a domain — ask, with suggestions."""
    print(f"\nNo domain specified for {STACKS[stack]}. Suggestions:")
    for i, s in enumerate(DOMAIN_SUGGESTIONS[:4], 1):
        print(f"  {i}. {s}")
    choice = input("\nPick a number, type your own domain, or 'you choose': ").strip()
    if choice.isdigit() and 1 <= int(choice) <= 4:
        return DOMAIN_SUGGESTIONS[int(choice) - 1]
    if not choice or choice.lower() in ("you choose", "choose", "any"):
        return "(your choice — pick a fresh domain that does not overlap the ledger)"
    return choice


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FS_GEN — generate-only coding-assessment question pipeline",
        epilog="Stacks: " + ", ".join(STACKS),
    )
    parser.add_argument("--stack", choices=list(STACKS))
    parser.add_argument("--difficulty", choices=["easy", "medium", "hard"])
    parser.add_argument("--domain", help="Domain/scenario; prompted interactively if omitted")
    parser.add_argument("--list", action="store_true", help="List the question ledger")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    await db_manager.initialize()
    try:
        if args.list:
            for q in await svc_db.db_list_questions():
                print(f"{q['question_id']} | {q['status']} | {q['tech_stack']} | {q['difficulty']}"
                      f" | {q['domain']} | {json.dumps(q['entities'])} | {q['core_business_rule']}")
            return
        if args.stack and args.difficulty:
            stack, difficulty = args.stack, args.difficulty
            domain = args.domain or _ask_domain(stack)
        else:
            stack, difficulty, domain = _interactive_mode()
        result = await run_generation_pipeline(stack, difficulty, domain)
        if result.get("status") != "complete":
            print(f"✗ failed: {result.get('error', 'unknown error')}", file=sys.stderr)
            sys.exit(1)
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

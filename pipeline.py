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
import time
from pathlib import Path

import structlog

from agents.stack_specs import DOMAIN_SUGGESTIONS, STACKS
from agents.tools import GENERATED_DIR
from core.config import settings
from core.database import db_manager
from services import db as svc_db
from services import file_io
from services import question as svc_q

logger = structlog.getLogger(__name__)


def _check_parity(skeleton_dir: str, solution_dir: str) -> dict:
    """Diff the trees; first repair any EMPTY orphan files (blank placeholders a
    generator sometimes creates in one tree only — see A-03 writing empty test.py).
    An empty file carries no work, so deleting it to restore parity is safe; a
    non-empty orphan is a real mismatch and stays in the returned diff."""
    diff = file_io.diff_file_trees(skeleton_dir, solution_dir)
    if diff["parity_ok"]:
        return diff
    removed = []
    for rel, base in ([(p, solution_dir) for p in diff["only_in_dir2"]]
                      + [(p, skeleton_dir) for p in diff["only_in_dir1"]]):
        f = Path(base) / rel
        if f.is_file() and not f.read_text(encoding="utf-8", errors="replace").strip():
            f.unlink()
            removed.append(rel)
    if removed:
        logger.info("parity_reconciled", removed_empty_orphans=removed)
        diff = file_io.diff_file_trees(skeleton_dir, solution_dir)
    return diff


async def _fail(question_id: str, result: dict, error: str) -> None:
    logger.error("pipeline_failed", question_id=question_id, error=error)
    result["status"] = "failed"
    result["error"] = error
    await svc_db.db_update_question_status(question_id, "failed")


async def _run_stage(question_id: str, result: dict, label: str, coro) -> dict | None:
    """Run one pipeline stage; convert any raised exception into a clean 'failed'
    status instead of crashing the whole run. Returns None if the stage failed.
    Prints duration + running token total after each stage and enforces the
    per-question token ceiling (QOS: a runaway fix loop dies here, not on the bill)."""
    t0 = time.monotonic()
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

    total_tokens = await svc_db.db_sum_agent_tokens(question_id)
    logger.info("stage_done", stage=label, question_id=question_id,
                duration_s=round(time.monotonic() - t0, 1), tokens_so_far=total_tokens)
    ceiling = settings.MAX_TOKENS_PER_QUESTION
    if ceiling and total_tokens > ceiling:
        await _fail(question_id, result,
                    f"token budget exceeded after {label} ({total_tokens:,} > {ceiling:,})")
        return None
    return stage_result


async def run_generation_pipeline(stack: str, difficulty: str, domain: str) -> dict:
    """Generate one question end to end. Returns the pipeline result dict."""
    from agents import designer, problem_statement, skeleton_generator, solution_generator, test_generator, validator

    GENERATED_DIR.mkdir(exist_ok=True)
    question_id = svc_q.generate_question_id(stack, difficulty, GENERATED_DIR)
    output_dir = str(GENERATED_DIR / question_id)
    result: dict = {"question_id": question_id, "output_dir": output_dir, "stages": {}}

    logger.info("pipeline_start", question_id=question_id, stack=stack,
                difficulty=difficulty, domain=domain)
    ledger = await svc_db.db_list_questions()
    await svc_db.db_create_question(question_id, STACKS[stack], difficulty, domain, output_dir)

    logger.info("stage_start", stage="A-01 Designer")
    design = await _run_stage(question_id, result, "A-01 Designer",
        designer.run(question_id, stack, difficulty, domain, ledger))
    if design is None:
        return result
    # Persist the design contract so --revalidate can re-run A-06 later without regenerating.
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    (Path(output_dir) / "design.json").write_text(
        json.dumps({k: v for k, v in design.items() if k != "status"}, indent=2))

    logger.info("stage_start", stage="A-02 Skeleton Generator")
    if await _run_stage(question_id, result, "A-02 Skeleton Generator",
            skeleton_generator.run(question_id, output_dir, stack, difficulty, design)) is None:
        return result

    logger.info("stage_start", stage="A-03 Solution Generator")
    if await _run_stage(question_id, result, "A-03 Solution Generator",
            solution_generator.run(question_id, output_dir, stack, difficulty, design)) is None:
        return result

    diff = _check_parity(f"{output_dir}/skeleton", f"{output_dir}/solution")
    if not diff["parity_ok"]:
        await _fail(question_id, result, f"skeleton/solution tree mismatch: {diff}")
        return result

    logger.info("stage_start", stage="A-04 Test Generator")
    if await _run_stage(question_id, result, "A-04 Test Generator",
            test_generator.run(question_id, output_dir, stack, difficulty, design)) is None:
        return result

    diff = _check_parity(f"{output_dir}/skeleton", f"{output_dir}/solution")
    if not diff["parity_ok"]:
        await _fail(question_id, result, f"tree mismatch after tests: {diff}")
        return result

    logger.info("stage_start", stage="A-06 Validator", note="executing test suites")
    if await _run_stage(question_id, result, "A-06 Validator",
            validator.run(question_id, output_dir, stack, difficulty, design)) is None:
        return result

    diff = _check_parity(f"{output_dir}/skeleton", f"{output_dir}/solution")
    if not diff["parity_ok"]:
        await _fail(question_id, result, f"tree mismatch after validation fixes: {diff}")
        return result

    logger.info("stage_start", stage="A-05 Problem Statement")
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

    # QOS: a question whose suites never actually ran must not look identical to a
    # validated one in the ledger — mark it 'unvalidated' so it's queryable and recoverable.
    val = result["stages"].get("A-06 Validator", {})
    validated = val.get("validation") not in ("skipped", "solution_only")
    final_status = "complete" if validated else "unvalidated"

    await svc_db.db_finalize_question(
        question_id=question_id,
        domain=design.get("domain", domain),
        entities=[e.get("name") for e in design.get("entities", [])],
        core_business_rule=design.get("core_business_rule", ""),
        problem_statement=statement_text,
        status=final_status,
    )

    total_tokens = await svc_db.db_sum_agent_tokens(question_id)
    result["status"] = final_status
    result["files_logged"] = len(manifest)
    result["total_tokens"] = total_tokens
    if not validated:
        logger.warning("shipped_unvalidated", question_id=question_id,
                       reason=val.get("reason", val.get("validation")),
                       recover=f"python pipeline.py --revalidate {question_id}")
    logger.info("pipeline_done", question_id=question_id, status=final_status,
                output_dir=output_dir, files=len(manifest), total_tokens=total_tokens)
    return result


async def run_revalidation_pipeline(question_id: str) -> dict:
    """Re-run A-06 on an existing question without regenerating anything — recovers
    'unvalidated' questions on a machine that can execute the stack."""
    from agents import validator

    q = await svc_db.db_get_question(question_id)
    if not q:
        return {"question_id": question_id, "status": "failed",
                "error": f"{question_id} not found in ledger"}
    slug = next((s for s, name in STACKS.items() if name == q["tech_stack"]), None)
    if slug is None:
        return {"question_id": question_id, "status": "failed",
                "error": f"unknown tech stack {q['tech_stack']!r}"}

    output_dir = q["output_dir"]
    design_path = Path(output_dir) / "design.json"
    design = (json.loads(design_path.read_text()) if design_path.exists()
              else {"domain": q["domain"], "entities": q["entities"],
                    "core_business_rule": q["core_business_rule"]})

    result: dict = {"question_id": question_id, "output_dir": output_dir, "stages": {}}
    logger.info("revalidate_start", question_id=question_id,
                tech_stack=q["tech_stack"], difficulty=q["difficulty"])
    if await _run_stage(question_id, result, "A-06 Validator",
            validator.run(question_id, output_dir, slug, q["difficulty"], design)) is None:
        return result

    val = result["stages"]["A-06 Validator"]
    validated = val.get("validation") not in ("skipped", "solution_only")
    final_status = "complete" if validated else "unvalidated"
    await svc_db.db_update_question_status(question_id, final_status)
    result["status"] = final_status
    result["total_tokens"] = await svc_db.db_sum_agent_tokens(question_id)
    logger.info("revalidation_done", question_id=question_id, status=final_status,
                total_tokens=result["total_tokens"])
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
    parser.add_argument("--revalidate", metavar="QUESTION_ID",
                        help="Re-run A-06 validation on an existing question (no regeneration)")
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
        if args.revalidate:
            result = await run_revalidation_pipeline(args.revalidate)
            if result.get("status") not in ("complete", "unvalidated"):
                print(f"✗ failed: {result.get('error', 'unknown error')}", file=sys.stderr)
                sys.exit(1)
            return
        if args.stack and args.difficulty:
            stack, difficulty = args.stack, args.difficulty
            domain = args.domain or _ask_domain(stack)
        else:
            stack, difficulty, domain = _interactive_mode()
        result = await run_generation_pipeline(stack, difficulty, domain)
        # 'unvalidated' is generation success with a QOS warning, not a failure.
        if result.get("status") not in ("complete", "unvalidated"):
            print(f"✗ failed: {result.get('error', 'unknown error')}", file=sys.stderr)
            sys.exit(1)
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

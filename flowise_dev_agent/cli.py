"""Interactive CLI for the Flowise Dev Agent.

Runs the full discover → plan → patch → test → converge loop directly in
the terminal — no HTTP server or curl required.

Usage:
    flowise-agent-cli build "Build a customer support chatbot with GPT-4o"
    flowise-agent-cli build "requirement" --trials 2
"""

from __future__ import annotations

import asyncio
import logging
import sys
from argparse import ArgumentParser
from uuid import uuid4


# ---------------------------------------------------------------------------
# Core interactive session runner
# ---------------------------------------------------------------------------


async def _run_session(requirement: str, trials: int = 1) -> None:
    """Run an interactive build session, prompting the developer at each HITL point."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from flowise_dev_agent.agent import create_agent
    from flowise_dev_agent.api import _initial_state
    from langgraph.types import Command

    graph, client = create_agent_from_env()

    thread_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print(f"\nSession : {thread_id}")
    print(f"Building: {requirement}\n")
    print("-" * 60)

    try:
        await graph.ainvoke(_initial_state(requirement, trials), config=config)

        while True:
            snapshot = graph.get_state(config)
            interrupts = [
                intr.value
                for task in snapshot.tasks
                for intr in getattr(task, "interrupts", [])
            ]

            if not interrupts:
                print("\nSession complete.")
                chatflow_id = snapshot.values.get("chatflow_id")
                if chatflow_id:
                    print(f"Chatflow ID: {chatflow_id}")
                break

            raw = interrupts[0]
            interrupt_type = raw.get("type", "unknown")

            print(f"\n{'=' * 60}")
            print(f"CHECKPOINT: {interrupt_type.upper()}")
            print("=" * 60)

            if interrupt_type == "plan_approval":
                print("\nPLAN:\n")
                print(raw.get("plan", "(no plan text)"))
                print(f"\n{raw.get('prompt', '')}")
                response = _prompt("Your response (or 'approved'): ")

            elif interrupt_type == "result_review":
                print("\nTEST RESULTS:\n")
                print(raw.get("test_results", "(no results)"))
                print(f"\n{raw.get('prompt', '')}")
                response = _prompt("Your response (or 'accepted'): ")

            elif interrupt_type == "credential_check":
                missing = raw.get("missing_credentials", [])
                if missing:
                    print(f"\nMissing credentials: {', '.join(missing)}")
                    print("Create them in Flowise (Settings → Credentials → Add New),")
                    print("then enter the credential ID(s) below.")
                print(f"\n{raw.get('prompt', '')}")
                response = _prompt("Credential ID(s): ")

            else:
                print(f"\nUnknown interrupt type: {interrupt_type!r}")
                print(f"Payload: {raw}")
                response = _prompt("Response: ")

            await graph.ainvoke(Command(resume=response), config=config)

    except KeyboardInterrupt:
        print("\n\nInterrupted. Session ID for later reference:")
        print(f"  {thread_id}")
    finally:
        await client.close()


def _prompt(label: str) -> str:
    """Read a line from stdin, stripping whitespace. Exits on EOF."""
    try:
        return input(label).strip()
    except EOFError:
        print("\n(EOF received — exiting)")
        sys.exit(0)


def create_agent_from_env():
    """Create a graph + client pair using environment variables.

    Uses MemorySaver (in-memory) — sessions are ephemeral within the CLI process.
    For persistent sessions, use the HTTP server (flowise-agent serve).
    """
    from flowise_dev_agent.agent import create_agent
    from flowise_dev_agent.client import Settings
    from flowise_dev_agent.reasoning import ReasoningSettings

    settings = Settings.from_env()
    reasoning_settings = ReasoningSettings.from_env()
    return create_agent(settings, reasoning_settings)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = ArgumentParser(
        prog="flowise-agent-cli",
        description="Flowise Dev Agent — interactive terminal client",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    build_p = sub.add_parser("build", help="Build a new Flowise chatflow interactively")
    build_p.add_argument("requirement", help="Natural-language description of what to build")
    build_p.add_argument(
        "--trials",
        type=int,
        default=1,
        metavar="K",
        help="pass^k reliability trials per test case (default: 1)",
    )

    args = parser.parse_args()

    if args.command == "build":
        asyncio.run(_run_session(args.requirement, args.trials))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

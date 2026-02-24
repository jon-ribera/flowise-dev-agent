"""Frontend simulation script.

Mimics exactly what the browser UI does:
  1. POST /sessions           → discover + plan → plan_approval interrupt
  2. (display plan for review)
  3. POST /sessions/{id}/resume → patch + test + converge → result_review interrupt
  4. POST /sessions/{id}/resume → accept result → completed

Run: python simulate_frontend.py [--requirement "..."] [--no-resume]

Flags
-----
--no-resume   Stop after displaying the plan (don't send approval).
--requirement Override the default requirement string.
"""

import argparse
import json
import sys
import time
import httpx

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError for emoji)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"

# ---------------------------------------------------------------------------
# Default requirement (moderate complexity — 5-node RAG chatflow)
# ---------------------------------------------------------------------------
DEFAULT_REQUIREMENT = (
    "Build a conversational RAG chatflow. "
    "Use GPT-4o-mini as the LLM (model chatOpenAI), OpenAI Embeddings "
    "(openAIEmbeddings), an in-memory vector store (memoryVectorStore), "
    "buffer window memory (bufferWindowMemory), and wire them together "
    "with a conversational retrieval QA chain (conversationalRetrievalQAChain). "
    "Set temperature to 0.3, k=5 for retrieval, windowSize=10 for memory. "
    "Bind the OpenAI credential to both the LLM and the embeddings nodes. "
    "Name the chatflow 'RAG Demo — GPT-4o-mini'."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hdr(title: str) -> None:
    width = 72
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def _pretty(obj: object) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _interrupt_summary(body: dict) -> None:
    interrupt = body.get("interrupt") or {}
    itype = interrupt.get("type", "?")
    print(f"\n  interrupt type : {itype}")

    if itype == "plan_approval":
        plan = interrupt.get("plan", "")
        if plan:
            print("\n--- PLAN ---")
            print(plan)
        else:
            print("  (no plan text returned)")
        mcreds = interrupt.get("missing_credentials")
        if mcreds:
            print(f"\n  MISSING CREDENTIALS: {mcreds}")

    elif itype == "result_review":
        cid = interrupt.get("chatflow_id") or body.get("chatflow_id", "?")
        print(f"\n  chatflow_id : {cid}")
        tr = interrupt.get("test_results") or {}
        passed = tr.get("passed", interrupt.get("test_passed", "?"))
        print(f"  test_passed : {passed}")
        msg = interrupt.get("message") or body.get("message", "")
        if msg:
            print(f"\n  message:\n{msg}")
        if tr:
            print("\n  test_results:")
            _pretty(tr)

    else:
        _pretty(interrupt)


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

def simulate(requirement: str, resume: bool, timeout: int) -> None:
    client = httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------
    # STEP 1 — Start session
    # ------------------------------------------------------------------
    _hdr("STEP 1: POST /sessions  (discover + plan)")
    print(f"\n  requirement: {requirement[:120]}{'...' if len(requirement) > 120 else ''}\n")

    t0 = time.time()
    r = client.post(f"{BASE}/sessions", json={"requirement": requirement, "test_trials": 1})
    elapsed = time.time() - t0
    print(f"  HTTP {r.status_code}  ({elapsed:.1f}s)")

    if r.status_code != 200:
        print("\nERROR response body:")
        try:
            _pretty(r.json())
        except Exception:
            print(r.text)
        sys.exit(1)

    body1 = r.json()
    thread_id = body1.get("thread_id", "")
    status1 = body1.get("status", "")

    print(f"  thread_id : {thread_id}")
    print(f"  status    : {status1}")
    _interrupt_summary(body1)

    if not resume:
        _hdr("STOPPED (--no-resume flag set)")
        return

    if status1 == "completed":
        _hdr("Session completed in one shot (no resume needed)")
        _pretty(body1)
        return

    if status1 != "pending_interrupt":
        _hdr("Unexpected status — aborting")
        _pretty(body1)
        sys.exit(1)

    # ------------------------------------------------------------------
    # STEP 2 — Resume: approve plan
    # ------------------------------------------------------------------
    _hdr("STEP 2: POST /sessions/{id}/resume  (approve plan → patch + test + converge)")
    print(f"\n  Sending: {{\"response\": \"approved\"}}\n")

    t1 = time.time()
    r2 = client.post(
        f"{BASE}/sessions/{thread_id}/resume",
        json={"response": "approved"},
    )
    elapsed2 = time.time() - t1
    print(f"  HTTP {r2.status_code}  ({elapsed2:.1f}s)")

    if r2.status_code != 200:
        print("\nERROR response body:")
        try:
            _pretty(r2.json())
        except Exception:
            print(r2.text)
        sys.exit(1)

    body2 = r2.json()
    status2 = body2.get("status", "")
    print(f"  status    : {status2}")
    _interrupt_summary(body2)

    if status2 != "pending_interrupt":
        _hdr("Final state")
        _pretty(body2)
        return

    itype2 = (body2.get("interrupt") or {}).get("type", "")
    if itype2 != "result_review":
        _hdr(f"Unexpected interrupt type '{itype2}' — inspect and resume manually")
        _pretty(body2)
        sys.exit(0)

    # ------------------------------------------------------------------
    # STEP 3 — Resume: accept result
    # ------------------------------------------------------------------
    _hdr("STEP 3: POST /sessions/{id}/resume  (accept result → completed)")
    print(f"\n  Sending: {{\"response\": \"accepted\"}}\n")

    t2 = time.time()
    r3 = client.post(
        f"{BASE}/sessions/{thread_id}/resume",
        json={"response": "accepted"},
    )
    elapsed3 = time.time() - t2
    print(f"  HTTP {r3.status_code}  ({elapsed3:.1f}s)")

    body3 = r3.json()
    status3 = body3.get("status", "")
    print(f"  status    : {status3}")

    _hdr("FINAL RESULT")
    _pretty(body3)

    if status3 == "completed":
        interrupt3 = body3.get("interrupt") or {}
        cid = interrupt3.get("chatflow_id") or body3.get("chatflow_id", "")
        if cid:
            print(f"\n  Flowise chatflow created: {cid}")
            print(f"  View at: http://localhost:3000/chatflows/{cid}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate a frontend session against the agent API.")
    parser.add_argument("--requirement", default=DEFAULT_REQUIREMENT, help="Requirement string to send")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Stop after plan display")
    parser.add_argument("--timeout", type=int, default=300, help="HTTP timeout in seconds (default 300)")
    args = parser.parse_args()

    simulate(requirement=args.requirement, resume=args.resume, timeout=args.timeout)

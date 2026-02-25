import { test, expect } from "@playwright/test";
import { SessionDetailPage } from "../pages/session-detail.page";

/**
 * J3 — Iteration: plan rejected, feedback sent, plan re-runs
 *
 * S3e (Plan Approval) → user types feedback
 * → streaming → plan_v2 re-runs → hitl_plan_v2 INTERRUPT again
 * → user approves
 */
test.describe("J3 — Iteration", () => {
  test.skip(
    !process.env.RUN_E2E_LIVE,
    "Skipped: set RUN_E2E_LIVE=1 to run against a live backend"
  );

  test("sending plan feedback increments iteration", async ({ page }) => {
    const detail = new SessionDetailPage(page);
    // TODO: start session, wait for plan_approval interrupt
    // TODO: fill feedback textarea, submit
    // TODO: assert iteration counter increments in header
    await page.goto("/sessions/test-session-002");
    await detail.waitForLoad();
  });

  test("approach chips appear when plan has options", async ({ page }) => {
    const detail = new SessionDetailPage(page);
    await page.goto("/sessions/test-session-002");
    await detail.waitForLoad();
    // TODO: mock plan_approval interrupt with options array
    // TODO: assert approach chips are rendered
    // TODO: assert Approve button is disabled until chip selected
  });

  test("approve selected approach sends correct response", async ({ page }) => {
    const detail = new SessionDetailPage(page);
    await page.goto("/sessions/test-session-002");
    await detail.waitForLoad();
    // TODO: select approach chip, click approve, assert SSE response includes approach label
  });
});

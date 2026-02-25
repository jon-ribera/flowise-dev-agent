import { test, expect } from "@playwright/test";
import { SessionDetailPage } from "../pages/session-detail.page";
import { SessionListPage } from "../pages/session-list.page";

/**
 * J4 — Open existing interrupted session (load from API on page load)
 * J5 — SSE reconnect after network drop
 */
test.describe("J4 — Open existing session", () => {
  test("opening interrupted session shows correct HITL panel", async ({ page }) => {
    // TODO: mock GET /sessions/{id} returning pending_interrupt with plan_approval
    // TODO: assert plan approval panel is immediately visible without waiting for SSE
    const detail = new SessionDetailPage(page);
    await detail.goto("test-session-002");
    await detail.waitForLoad();
    // For now just assert the page loads
    await expect(page).toHaveURL("/sessions/test-session-002");
  });

  test("completed session shows completed panel", async ({ page }) => {
    const detail = new SessionDetailPage(page);
    await detail.goto("test-session-001");
    await detail.waitForLoad();
    // TODO: mock GET /sessions/{id} returning completed
    // TODO: assert "Built Successfully" header is visible
  });

  test("phase timeline replays from after_seq=0 on page load", async ({ page }) => {
    const detail = new SessionDetailPage(page);
    await detail.goto("test-session-001");
    await detail.waitForLoad();
    // TODO: intercept GET /sessions/{id}/stream?after_seq=0 and assert it's called
  });
});

test.describe("J5 — SSE reconnect", () => {
  test("reconnect indicator shown after SSE disconnect", async ({ page }) => {
    // TODO: simulate network drop, assert reconnect indicator appears
    // TODO: assert reconnect URL includes after_seq=<last_seq>
    await page.goto("/sessions/test-session-001");
    await page.waitForLoadState("networkidle");
  });

  test("missed events replayed on reconnect", async ({ page }) => {
    // TODO: intercept SSE, disconnect, reconnect, assert events deduped
    await page.goto("/sessions/test-session-001");
    await page.waitForLoadState("networkidle");
  });
});

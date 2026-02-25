import { test, expect } from "@playwright/test";
import { SessionListPage } from "../pages/session-list.page";
import { NewSessionModalPage } from "../pages/new-session-modal.page";
import { SessionDetailPage } from "../pages/session-detail.page";

/**
 * J2 — UPDATE: select target chatflow
 *
 * / → new session → requirement implying update
 * → classify_intent → operation_mode: "update"
 * → hitl_select_target INTERRUPT → select_target panel
 * → select chatflow → continue
 */
test.describe("J2 — UPDATE: select target", () => {
  test.skip(
    !process.env.RUN_E2E_LIVE,
    "Skipped: set RUN_E2E_LIVE=1 to run against a live backend"
  );

  test("update requirement triggers select_target panel", async ({ page }) => {
    const listPage = new SessionListPage(page);
    const modal = new NewSessionModalPage(page);
    const detail = new SessionDetailPage(page);

    await listPage.goto();
    await listPage.clickNewSession();
    await modal.fillRequirement("Update the customer support chatbot to use Claude instead of GPT-4o");
    await modal.submit();

    await expect(page).toHaveURL(/\/sessions\/.+/);

    // Wait for select_target interrupt
    // TODO: wait for SSE interrupt event and assert panel is visible
    await detail.waitForLoad();
  });

  test("update selected button disabled until row selected", async ({ page }) => {
    const detail = new SessionDetailPage(page);
    await page.goto("/sessions/test-session-002");
    await detail.waitForLoad();
    // TODO: mock select_target interrupt and assert button state
  });

  test("create new instead sends correct response", async ({ page }) => {
    const detail = new SessionDetailPage(page);
    await page.goto("/sessions/test-session-002");
    await detail.waitForLoad();
    // TODO: assert "Create New Instead" button triggers correct SSE response
  });
});

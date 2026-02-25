import { test, expect } from "@playwright/test";
import { SessionListPage } from "../pages/session-list.page";
import { NewSessionModalPage } from "../pages/new-session-modal.page";
import { SessionDetailPage } from "../pages/session-detail.page";

/**
 * J1 — CREATE happy path
 *
 * / → click "+ New Session" → fill requirement → submit
 * → /sessions/[id] → streaming → plan_approval INTERRUPT
 * → approve plan → result_review INTERRUPT → accept → completed
 *
 * NOTE: These tests require a running backend (localhost:8000) and Flowise (localhost:3000).
 * They are skipped in unit CI via the test.skip condition below.
 */
test.describe("J1 — CREATE happy path", () => {
  test.skip(
    !process.env.RUN_E2E_LIVE,
    "Skipped: set RUN_E2E_LIVE=1 to run against a live backend"
  );

  test("navigates to session detail after form submit", async ({ page }) => {
    const listPage = new SessionListPage(page);
    const modal = new NewSessionModalPage(page);

    await listPage.goto();
    await listPage.clickNewSession();
    await modal.assertVisible();
    await modal.fillRequirement("Build a basic customer support chatbot using GPT-4o");
    await modal.submit();

    // Should navigate to /sessions/[uuid]
    await expect(page).toHaveURL(/\/sessions\/.+/);
  });

  test("phase timeline appears on session detail", async ({ page }) => {
    const listPage = new SessionListPage(page);
    const modal = new NewSessionModalPage(page);
    const detail = new SessionDetailPage(page);

    await listPage.goto();
    await listPage.clickNewSession();
    await modal.fillRequirement("Build a basic RAG chatbot");
    await modal.submit();

    await expect(page).toHaveURL(/\/sessions\/.+/);
    // TODO: assert phase timeline renders with at least one node
    await detail.waitForLoad();
  });

  test("Ctrl+Enter submits the form", async ({ page }) => {
    const listPage = new SessionListPage(page);
    const modal = new NewSessionModalPage(page);

    await listPage.goto();
    await listPage.clickNewSession();
    await modal.fillRequirement("Build a simple echo bot");
    await modal.submitWithCtrlEnter();

    await expect(page).toHaveURL(/\/sessions\/.+/);
  });
});

import { test, expect } from "@playwright/test";
import { SessionListPage } from "../pages/session-list.page";

/**
 * Smoke test — verifies the UI loads and the session list is reachable.
 * This is the only test that must pass in CI without a running backend.
 */
test.describe("Smoke", () => {
  test("session list page loads", async ({ page }) => {
    const listPage = new SessionListPage(page);
    await listPage.goto();
    await listPage.waitForLoad();

    // The page should render — either empty state or session rows
    await expect(page).toHaveTitle(/flowise dev agent/i);
    await expect(page.locator("h1")).toBeVisible();
  });

  test("new session button is visible", async ({ page }) => {
    const listPage = new SessionListPage(page);
    await listPage.goto();
    await listPage.waitForLoad();
    await expect(listPage.newSessionButton).toBeVisible();
  });

  test("clicking new session opens modal", async ({ page }) => {
    const listPage = new SessionListPage(page);
    await listPage.goto();
    await listPage.waitForLoad();
    await listPage.clickNewSession();
    await expect(page.getByRole("heading", { name: /new session/i })).toBeVisible();
  });
});

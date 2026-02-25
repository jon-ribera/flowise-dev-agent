import { type Page, type Locator, expect } from "@playwright/test";

/**
 * Page Object: Session List (S1 — Dashboard)
 * Route: /
 */
export class SessionListPage {
  readonly page: Page;
  readonly newSessionButton: Locator;
  readonly sessionTable: Locator;
  readonly emptyState: Locator;
  readonly refreshButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.newSessionButton = page.getByRole("button", { name: /new session/i });
    this.sessionTable = page.locator('[data-testid="session-list"]').or(page.locator(".space-y-1"));
    this.emptyState = page.getByText(/no sessions yet/i);
    this.refreshButton = page.getByRole("button", { name: /refresh/i });
  }

  async goto() {
    await this.page.goto("/");
  }

  async waitForLoad() {
    await this.page.waitForLoadState("networkidle");
  }

  async clickNewSession() {
    await this.newSessionButton.click();
  }

  async getSessionRows() {
    return this.page.locator('[role="button"][tabindex="0"]').all();
  }

  async clickSessionRow(index: number) {
    const rows = await this.getSessionRows();
    await rows[index].click();
  }

  async getSessionCount() {
    const rows = await this.getSessionRows();
    return rows.length;
  }

  async assertStatusBadgeVisible(label: string) {
    await expect(this.page.getByText(label)).toBeVisible();
  }
}

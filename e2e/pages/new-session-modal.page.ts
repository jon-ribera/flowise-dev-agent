import { type Page, type Locator, expect } from "@playwright/test";

/**
 * Page Object: New Session Modal (S2)
 */
export class NewSessionModalPage {
  readonly page: Page;
  readonly requirementTextarea: Locator;
  readonly testTrialsInput: Locator;
  readonly submitButton: Locator;
  readonly cancelButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.requirementTextarea = page.getByPlaceholder(/describe what you want/i);
    this.testTrialsInput = page.locator('input[type="number"]');
    this.submitButton = page.getByRole("button", { name: /start session/i });
    this.cancelButton = page.getByRole("button", { name: /cancel/i });
  }

  async assertVisible() {
    await expect(this.page.getByRole("heading", { name: /new session/i })).toBeVisible();
  }

  async fillRequirement(requirement: string) {
    await this.requirementTextarea.fill(requirement);
  }

  async setTestTrials(n: number) {
    await this.testTrialsInput.fill(String(n));
  }

  async submit() {
    await this.submitButton.click();
  }

  async submitWithCtrlEnter() {
    await this.requirementTextarea.press("Control+Enter");
  }

  async cancel() {
    await this.cancelButton.click();
  }

  async assertSubmitDisabledWhenEmpty() {
    await expect(this.submitButton).toBeDisabled();
  }
}

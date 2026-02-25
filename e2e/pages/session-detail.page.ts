import { type Page, type Locator, expect } from "@playwright/test";

/**
 * Page Object: Session Detail (S3)
 * Route: /sessions/[id]
 */
export class SessionDetailPage {
  readonly page: Page;
  readonly phaseTimeline: Locator;
  readonly activePanel: Locator;
  readonly artifactsPanel: Locator;

  // HITL panels
  readonly planApprovalPanel: Locator;
  readonly resultReviewPanel: Locator;
  readonly selectTargetPanel: Locator;
  readonly credentialCheckPanel: Locator;
  readonly clarificationPanel: Locator;

  // Plan Approval actions
  readonly approvePlanButton: Locator;
  readonly sendChangesButton: Locator;

  // Result Review actions
  readonly acceptDoneButton: Locator;
  readonly rollbackButton: Locator;
  readonly requestChangesButton: Locator;

  // Select Target actions
  readonly updateSelectedButton: Locator;
  readonly createNewButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.phaseTimeline = page.getByRole("navigation", { name: /phase timeline/i });
    this.activePanel = page.locator("main");
    this.artifactsPanel = page.locator("aside").last();

    this.planApprovalPanel = page.getByText(/plan ready for review/i);
    this.resultReviewPanel = page.getByText(/tests complete/i);
    this.selectTargetPanel = page.getByText(/select chatflow to update/i);
    this.credentialCheckPanel = page.getByText(/credential check/i);
    this.clarificationPanel = page.getByText(/clarification needed/i);

    this.approvePlanButton = page.getByRole("button", { name: /approve plan/i });
    this.sendChangesButton = page.getByRole("button", { name: /send changes/i });

    this.acceptDoneButton = page.getByRole("button", { name: /accept.*done/i });
    this.rollbackButton = page.getByRole("button", { name: /rollback/i });
    this.requestChangesButton = page.getByRole("button", { name: /request changes/i });

    this.updateSelectedButton = page.getByRole("button", { name: /update selected/i });
    this.createNewButton = page.getByRole("button", { name: /create new instead/i });
  }

  async goto(sessionId: string) {
    await this.page.goto(`/sessions/${sessionId}`);
  }

  async waitForLoad() {
    await this.page.waitForLoadState("networkidle");
  }

  // Plan Approval helpers

  async approvePlan() {
    await this.approvePlanButton.click();
  }

  async approvePlanWithApproach(approachLabel: string) {
    await this.page.getByRole("button", { name: approachLabel }).click();
    await this.approvePlanButton.click();
  }

  async sendPlanFeedback(feedback: string) {
    await this.page.getByPlaceholder("approved").fill(feedback);
    await this.sendChangesButton.click();
  }

  // Result Review helpers

  async acceptResult() {
    await this.acceptDoneButton.click();
  }

  async requestResultChanges(feedback: string) {
    await this.page.locator("textarea").last().fill(feedback);
    await this.requestChangesButton.click();
  }

  // Select Target helpers

  async selectTargetRow(index: number) {
    const rows = await this.page.locator('[role="button"][tabindex="0"]').all();
    await rows[index].click();
  }

  async confirmUpdateSelected() {
    await this.updateSelectedButton.click();
  }

  async createNewInstead() {
    await this.createNewButton.click();
  }

  // Phase Timeline helpers

  async getNodeStatus(nodeName: string): Promise<string | null> {
    const node = this.page.getByText(nodeName, { exact: true }).first();
    const parent = node.locator("..");
    return parent.getAttribute("class");
  }

  async assertPhaseNodeCompleted(nodeName: string) {
    // Completed nodes have a check icon
    await expect(this.page.getByText("✓").first()).toBeVisible();
  }

  // Artifacts Panel helpers

  async openArtifactsTab(tab: "Plan" | "Tests" | "Versions" | "Telemetry" | "Patterns") {
    await this.page.getByRole("button", { name: tab }).click();
  }
}

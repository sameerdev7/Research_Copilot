import { expect, test } from "@playwright/test";

test("sign in, ask, follow up, and find the history after a reload", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Username").fill("demo");
  await page.getByLabel("Password").fill("demo-pass-12345");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("button", { name: "New chat" })).toBeVisible();

  const composer = page.getByPlaceholder("Ask a question about your papers");
  await composer.fill("What does the Transformer use instead of recurrence?");
  await composer.press("Enter");

  await expect(page.getByRole("status")).toBeVisible();
  await expect(page.getByText("(demo mode)")).toBeVisible();
  await expect(page.getByText("Every claim checked against its source")).toBeVisible();

  await page.getByRole("button", { name: "Show 1 source" }).click();
  await expect(page.getByRole("link", { name: /Attention Is All You Need/ })).toBeVisible();

  await composer.fill("And how was it trained?");
  await composer.press("Enter");
  await expect(page.getByText("(demo mode)")).toHaveCount(2);

  await page.reload();
  await expect(page.getByText("And how was it trained?")).toBeVisible();
  await expect(page.locator(".chat-item")).toHaveCount(1);
});

test("diagnostics panel reports system health", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Username").fill("demo");
  await page.getByLabel("Password").fill("demo-pass-12345");
  await page.getByRole("button", { name: "Sign in" }).click();

  await page.getByRole("button", { name: /Needs attention|All systems ok|Diagnostics/ }).click();
  const dialog = page.getByRole("dialog", { name: "System diagnostics" });
  await expect(dialog.getByText("Postgres and pgvector are ready.")).toBeVisible();
  await expect(dialog.getByText("Demo mode")).toBeVisible();
});

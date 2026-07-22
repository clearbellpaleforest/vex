// @ts-check
const { test, expect } = require('@playwright/test');

test('mesh GUI loads', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/Vex/);
});

test('mesh GUI is responsive', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('body')).toBeVisible();
});

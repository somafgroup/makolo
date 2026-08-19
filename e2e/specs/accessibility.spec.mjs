import { test, expect } from '../fixtures/makolo.mjs';
import { expectNoSeriousAxeViolations } from '../helpers/accessibility.mjs';
import { login } from '../helpers/auth.mjs';


async function audit(page, path) {
  const response = await page.goto(path);
  expect(response.status()).toBeLessThan(500);
  await expectNoSeriousAxeViolations(page);
}


test('public and account entry surfaces have no serious or critical axe violations', async ({ page }) => {
  await audit(page, '/');
  await audit(page, '/login/');
  await audit(page, '/account/register/');
  await audit(page, '/discover/');
  await audit(page, '/events/festival-makolo-e2e/');
  await audit(page, '/page-e2e-a11y-404/');
});


test('participant home, Journey and Access surfaces pass axe gate', async ({ page }) => {
  await login(page, 'participant@e2e.makolo.test');
  await audit(page, '/dashboard/');
  await audit(page, '/account/');
  await audit(page, '/account/profile/');
  await audit(page, '/account/journeys/');
  await audit(page, '/account/accesses/');
  await page.getByText('Atelier citoyen Makolo E2E').first().click();
  await expectNoSeriousAxeViolations(page);
});


test('scanner organization and Operations surfaces pass axe gate', async ({ page }) => {
  await login(page, 'scanner@e2e.makolo.test');
  await audit(page, '/scanner/event/festival-makolo-e2e/');

  await page.context().clearCookies();
  await login(page, 'owner@e2e.makolo.test');
  await audit(page, '/dashboard/');

  await page.context().clearCookies();
  await login(page, 'staff@e2e.makolo.test');
  await audit(page, '/operations/');

  await page.context().clearCookies();
  await login(page, 'participant@e2e.makolo.test');
  const response = await page.goto('/events/new/');
  expect(response.status()).toBe(403);
  await expectNoSeriousAxeViolations(page);
});

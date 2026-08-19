import { test, expect } from '../fixtures/makolo.mjs';
import { login } from '../helpers/auth.mjs';

async function expectNoHorizontalOverflow(page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}


test('participant home, profile and canonical Access QR stay usable on mobile @mobile', async ({ page }) => {
  await page.goto('/events/festival-makolo-e2e/');
  await expect(page.getByRole('link', { name: /Obtenir des billets/i })).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await login(page, 'participant@e2e.makolo.test');
  await page.goto('/account/');
  await expect(page.getByRole('heading', { name: 'Mon espace' })).toBeVisible();
  await expect(page.getByText('Atelier citoyen Makolo E2E').first()).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.goto('/account/profile/');
  await expect(page.getByRole('heading', { name: 'Mon profil' })).toBeVisible();
  await expect(page.getByRole('button', { name: /Enregistrer mon profil/i })).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.goto('/account/accesses/');
  await page.getByText('Atelier citoyen Makolo E2E').first().click();
  await expect(page.getByRole('img', { name: /QR de ma confirmation/i })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});


test('scanner and Operations remain reachable at phone width @mobile', async ({ page }) => {
  await login(page, 'scanner@e2e.makolo.test');
  await page.goto('/scanner/event/festival-makolo-e2e/');
  await expect(page.getByText('Lire une image QR')).toBeVisible();
  await expect(page.getByLabel('Saisie manuelle du jeton QR')).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.context().clearCookies();
  await login(page, 'staff@e2e.makolo.test');
  await page.goto('/operations/');
  await expect(page.getByRole('heading', { name: 'Makolo Operations Center' })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

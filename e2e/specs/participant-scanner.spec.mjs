import { test, expect } from '../fixtures/makolo.mjs';
import { login, logout } from '../helpers/auth.mjs';


async function createPaidOrder(page) {
  await page.goto('/discover/');
  await page.getByRole('link', { name: 'Festival Makolo E2E' }).first().click();
  await page.getByRole('link', { name: /Obtenir des billets/i }).click();
  await page.getByLabel('Quantité').fill('1');
  await page.getByRole('button', { name: /Créer la commande/i }).click();
  await expect(page.getByText('Pass standard E2E')).toBeVisible();
}


async function completeSandboxPayment(page) {
  await page.getByRole('link', { name: /Payer maintenant/i }).click();
  await page.locator('[name="provider"]').selectOption('sandbox');
  const method = page.locator('[name="method"]');
  if (await method.locator('option').count() > 1) await method.selectOption({ index: 1 });
  await page.getByRole('button', { name: /Initialiser le paiement/i }).click();
  await expect(page.getByText(/Sandbox/i)).toBeVisible();
  await page.getByRole('button', { name: /Simuler un paiement réussi/i }).click();
  await expect(page.getByText(/Paiement confirmé/i).first()).toBeVisible();
}


test('participant goes from discovery to payment, Journey, Access QR, accepted scan then duplicate refusal', async ({ page }, testInfo) => {
  await login(page, 'participant@e2e.makolo.test');
  await expect(page.getByText(/Espace participant/i)).toBeVisible();

  await page.goto('/discover/for-you/');
  await expect(page.getByRole('heading').filter({ hasText: /Pour vous|Sélection/i }).first()).toBeVisible();
  await page.goto('/discover/');
  await page.getByRole('link', { name: 'Festival Makolo E2E' }).first().click();
  await page.getByRole('button', { name: /Enregistrer/i }).click();
  await expect(page.getByRole('button', { name: /Enregistré/i })).toBeVisible();
  await page.goto('/discover/bookmarks/');
  await expect(page.getByText('Festival Makolo E2E').first()).toBeVisible();

  await page.getByRole('link', { name: 'Festival Makolo E2E' }).first().click();
  await page.getByRole('link', { name: /Obtenir des billets/i }).click();
  await page.getByLabel('Quantité').fill('1');
  await page.getByRole('button', { name: /Créer la commande/i }).click();
  await completeSandboxPayment(page);

  await page.goto('/notifications/');
  await expect(page.getByRole('heading', { name: 'Paiement confirmé', exact: true })).toHaveCount(1);
  await expect(page.getByRole('heading', { name: 'Vos billets sont disponibles', exact: true })).toHaveCount(1);

  await page.goto('/account/journeys/');
  const festivalJourney = page.locator('article').filter({ hasText: 'Festival Makolo E2E' }).first();
  await expect(festivalJourney).toBeVisible();
  await festivalJourney.getByRole('link', { name: /Voir mon billet/i }).click();
  const accessUrl = page.url();
  await expect(page.getByText('Billet valide', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Pass standard E2E')).toBeVisible();

  const qrPath = testInfo.outputPath('purchased-access-qr.png');
  await page.getByRole('img', { name: /QR de mon billet/i }).screenshot({ path: qrPath });

  await logout(page);
  await login(page, 'scanner@e2e.makolo.test');
  await page.goto('/scanner/');
  const eventCard = page.locator('article').filter({ hasText: 'Festival Makolo E2E' });
  await expect(eventCard).toBeVisible();
  await eventCard.getByRole('link', { name: 'Scanner' }).click();
  await expect(page.getByRole('heading', { name: 'Festival Makolo E2E' })).toBeVisible();
  await expect(page.getByText(/Saisie manuelle du jeton QR/i)).toBeVisible();
  await page.locator('#qr-image').setInputFiles(qrPath);
  await expect(page.getByRole('heading', { name: 'Accès autorisé' })).toBeVisible();

  await page.reload();
  await page.locator('#qr-image').setInputFiles(qrPath);
  await expect(page.getByRole('heading', { name: 'Accès refusé' })).toBeVisible();
  await expect(page.getByText(/déjà utilisé/i)).toBeVisible();
  await page.getByRole('link', { name: 'Historique' }).click();
  const scanRows = page.locator('tbody tr');
  await expect(scanRows.filter({ hasText: 'Accès autorisé' })).toHaveCount(1);
  await expect(scanRows.filter({ hasText: 'Billet déjà utilisé' })).toHaveCount(1);
  await expect(scanRows.filter({ hasText: 'Festival Makolo E2E' })).toHaveCount(2);

  await logout(page);
  await login(page, 'finance@e2e.makolo.test');
  await page.goto('/analytics/events/festival-makolo-e2e/');
  await expect(page.getByRole('heading', { name: 'Festival Makolo E2E' })).toBeVisible();
  await expect(page.getByText('1 scan(s) accepté(s)', { exact: true })).toBeVisible();
  const financeSection = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Revenus nets observés' }) });
  await expect(financeSection).toBeVisible();
  await expect(financeSection.getByText(/12[.,]00 USD/, { exact: true })).toBeVisible();

  await logout(page);
  await login(page, 'participant@e2e.makolo.test');
  await page.goto(accessUrl);
  await expect(page.getByText('Billet utilisé', { exact: true }).first()).toBeVisible();
});


test('canonical non-Event registration appears in home, Journey and Access without ticket vocabulary', async ({ page }) => {
  await login(page, 'participant@e2e.makolo.test');
  await page.goto('/account/');
  await expect(page.getByText('Atelier citoyen Makolo E2E').first()).toBeVisible();
  await expect(page.getByText('Maison Makolo E2E').first()).toBeVisible();

  await page.goto('/account/journeys/');
  const row = page.locator('article').filter({ hasText: 'Atelier citoyen Makolo E2E' }).first();
  await expect(row).toBeVisible();
  await row.getByRole('link', { name: /Voir ma confirmation/i }).click();
  await expect(page.getByText('Confirmation', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Inscription confirmée', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Maison Makolo E2E')).toBeVisible();
  await expect(page.getByRole('img', { name: /QR de ma confirmation/i })).toBeVisible();
  await expect(page.getByText(/Type de billet/i)).toHaveCount(0);
});


test('participant can accept a canonical invitation and receive Access', async ({ page }) => {
  await login(page, 'participant@e2e.makolo.test');
  await page.goto('/account/journeys/');
  const invitation = page.locator('article').filter({ hasText: 'Invitation Makolo E2E' }).first();
  await expect(invitation).toBeVisible();
  await invitation.getByRole('link', { name: /Répondre à l’invitation/i }).click();
  await expect(page.getByText('Invitation à accepter')).toBeVisible();
  await page.getByRole('button', { name: 'Accepter l’invitation' }).click();
  await expect(page.getByText('Invitation acceptée').first()).toBeVisible();
  await expect(page.getByRole('img', { name: /QR de mon invitation/i })).toBeVisible();
});


test('on-site reservation is presented as pay on site, never unpaid', async ({ page }) => {
  await login(page, 'profile.user@e2e.makolo.test');
  await page.goto('/account/journeys/');
  const reservation = page.locator('article').filter({ hasText: 'Réservation Makolo E2E' }).first();
  await expect(reservation).toBeVisible();
  await reservation.getByRole('link', { name: /Voir ma réservation/i }).click();
  await expect(page.getByText('À payer sur place')).toBeVisible();
  await expect(page.getByText('Impayé')).toHaveCount(0);
});


test('sandbox payment can be cancelled and retried without losing the order', async ({ page }) => {
  await login(page, 'profile.user@e2e.makolo.test');
  await createPaidOrder(page);
  const orderUrl = page.url();

  await page.getByRole('link', { name: /Payer maintenant/i }).click();
  await page.locator('[name="provider"]').selectOption('sandbox');
  const method = page.locator('[name="method"]');
  if (await method.locator('option').count() > 1) await method.selectOption({ index: 1 });
  await page.getByRole('button', { name: /Initialiser le paiement/i }).click();
  await page.getByRole('button', { name: /Annuler cette tentative/i }).click();
  await expect(page.getByText(/Tentative de paiement annulée/i)).toBeVisible();

  await page.goto(orderUrl);
  await expect(page.getByRole('link', { name: /Payer maintenant/i })).toBeVisible();
  await page.getByRole('link', { name: /Payer maintenant/i }).click();
  await page.locator('[name="provider"]').selectOption('sandbox');
  const retryMethod = page.locator('[name="method"]');
  if (await retryMethod.locator('option').count() > 1) await retryMethod.selectOption({ index: 1 });
  await page.getByRole('button', { name: /Initialiser le paiement/i }).click();
  await expect(page.getByRole('button', { name: /Simuler un paiement réussi/i })).toBeVisible();
});


test('a free Event consumes its last canonical place and becomes sold out', async ({ page }) => {
  await login(page, 'empty.participant@e2e.makolo.test');
  await page.goto('/events/capacite-makolo-e2e/');
  await page.getByRole('link', { name: /Obtenir des billets/i }).click();
  const orderFormUrl = page.url();
  await expect(page.getByText(/1 restant\(s\)/i)).toBeVisible();
  await page.getByLabel('Quantité').fill('1');
  await page.getByRole('button', { name: /Créer la commande/i }).click();
  await expect(page.getByText('Place unique E2E').first()).toBeVisible();

  await page.goto(orderFormUrl);
  await expect(page.getByText(/0 restant\(s\)/i)).toBeVisible();
  await expect(page.getByText(/Complet pour le moment|Indisponible/i)).toBeVisible();
});

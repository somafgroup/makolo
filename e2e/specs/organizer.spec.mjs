import { test, expect } from '../fixtures/makolo.mjs';
import { login, logout } from '../helpers/auth.mjs';


test('owner creates a complete event, publishes it and configures ticketing', async ({ page }) => {
  await login(page, 'owner@e2e.makolo.test');
  await page.getByRole('link', { name: /Créer un événement/i }).click();
  await expect(page.getByRole('heading', { name: 'Créer un événement', exact: true })).toBeVisible();

  await page.locator('[name="organization"]').selectOption({ label: 'Makolo E2E Events' });
  await page.locator('[name="title"]').fill('Conférence Organisateur E2E');
  await page.locator('[name="category"]').selectOption({ label: 'Culture E2E' });
  await page.locator('[name="venue"]').selectOption({ label: 'Centre Makolo E2E — Lubumbashi' });
  await page.locator('[name="short_description"]').fill('Événement créé entièrement depuis le navigateur.');
  await page.locator('[name="description"]').fill('Ce scénario valide la création, la publication et la billetterie organisateur.');
  await page.locator('[name="visibility"]').selectOption('public');
  await page.locator('[name="start_at"]').fill('2030-08-20T18:00');
  await page.locator('[name="end_at"]').fill('2030-08-20T21:00');
  await page.locator('[name="registration_start_at"]').fill('2029-12-01T00:00');
  await page.locator('[name="registration_end_at"]').fill('2030-08-20T17:00');
  await page.locator('[name="timezone"]').fill('Africa/Lubumbashi');
  await page.getByRole('button', { name: /Créer le brouillon/i }).click();

  await expect(page.getByRole('heading', { name: 'Conférence Organisateur E2E', exact: true })).toBeVisible();
  await expect(page.getByText('Brouillon', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Gérer', exact: true }).click();
  await page.getByRole('button', { name: 'Publier' }).click();
  await expect(page.getByText(/Événement publié/i)).toBeVisible();
  await expect(page.getByText('Publié', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Gérer', exact: true }).click();
  await page.getByRole('link', { name: /Configurer la billetterie/i }).click();
  await page.getByRole('link', { name: 'Nouveau type' }).click();
  await page.getByLabel('Événement').selectOption({ label: 'Conférence Organisateur E2E' });
  await page.getByLabel('Nom du billet').fill('Standard Organisateur E2E');
  await page.getByLabel('Description').fill('Billet créé par le parcours Playwright organisateur.');
  await page.getByLabel('Prix').fill('8.00');
  await page.getByLabel('Devise').fill('USD');
  await page.getByLabel('Stock total').fill('60');
  await page.getByLabel('Minimum par commande').fill('1');
  await page.getByLabel('Maximum par commande').fill('5');
  await page.getByRole('button', { name: /Créer le type de billet/i }).click();
  await expect(page.getByText(/Type de billet créé/i)).toBeVisible();
  await expect(page.getByText('Standard Organisateur E2E')).toBeVisible();

  await page.goto('/events/');
  await expect(page.getByText('Conférence Organisateur E2E').first()).toBeVisible();
  await page.goto('/dashboard/');
  await expect(page.getByText(/Espace organisation/i)).toBeVisible();
  await expect(page.getByText(/Billets vendus|Commandes/i).first()).toBeVisible();
});


test('new organizer empty state keeps the create-event next action visible', async ({ page }) => {
  await login(page, 'new.organizer@e2e.makolo.test');
  await expect(page.getByText(/Aucun événement à venir/i)).toBeVisible();
  await expect(page.getByRole('link', { name: /Créer un événement/i })).toBeVisible();
});


test('space owner creates a reusable place and another space owner is isolated', async ({ page }) => {
  await login(page, 'owner@e2e.makolo.test');
  await page.goto('/organizations/makolo-e2e-events/');
  await page.getByRole('link', { name: 'Lieux' }).click();
  await page.getByRole('link', { name: 'Ajouter un lieu' }).click();
  await page.getByLabel('Nom du lieu').fill('Agence Centre-ville');
  await page.getByLabel('Adresse').fill('12 avenue des Tests');
  await page.getByLabel('Ville / localité').fill('Lubumbashi');
  await page.getByLabel('Province / région').fill('Haut-Katanga');
  await page.getByLabel('Pays').fill('CD');
  await page.getByLabel('Latitude').fill('-11.664000');
  await page.getByLabel('Longitude').fill('27.479000');
  await page.getByLabel('Fuseau horaire').fill('Africa/Lubumbashi');
  await page.getByLabel('Rôle du lieu').selectOption('branch');
  await page.getByLabel('Lieu principal pour ce rôle').check();
  await page.getByRole('button', { name: 'Ajouter le lieu' }).click();

  const placeHeading = page.getByRole('heading', { name: 'Agence Centre-ville', exact: true });
  await expect(placeHeading).toBeVisible();
  await expect(page.getByText(/Coordonnées/)).toBeVisible();

  await logout(page);
  await login(page, 'new.organizer@e2e.makolo.test');
  const response = await page.goto('/organizations/makolo-e2e-events/places/');
  expect(response.status()).toBe(403);
  await expect(page.getByText(/Erreur 403/i)).toBeVisible();
  await expect(page.getByRole('heading', { name: /Cet espace n’est pas accessible/i })).toBeVisible();
});

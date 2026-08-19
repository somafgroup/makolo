import { expect } from '@playwright/test';

export const E2E_PASSWORD = 'Makolo-E2E-2026!';

export async function login(page, email, password = E2E_PASSWORD) {
  await page.goto('/login/');
  await page.getByLabel('Adresse e-mail').fill(email);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  await Promise.all([
    page.waitForURL(/\/dashboard\/$/),
    page.getByRole('button', { name: 'Se connecter' }).click(),
  ]);
  await expect(page.getByRole('heading', { name: /Bienvenue|Mon espace/ }).first()).toBeVisible();
}

export async function logout(page) {
  await page.getByRole('button', { name: 'Menu utilisateur' }).click();
  await page.getByRole('menuitem', { name: 'Se déconnecter' }).click();
  await page.waitForURL('/');
}

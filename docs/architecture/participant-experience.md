# Participant Experience Makolo

## Principe

La Participant Experience présente le cœur canonique avec un vocabulaire naturel. Elle n'impose pas à l'utilisateur de connaître les objets techniques `Journey`, `Occurrence`, `Offer`, `CapacityPool`, `CommerceOrder` ou `AccessCredential`.

Le parcours de référence est :

```text
Occurrence
    ↓
Journey
    ↓
prochaine action participant
    ↓
Commerce / Payment si nécessaire
    ↓
Access
    ↓
Credential si nécessaire
```

`Activity` reste l'identité durable de ce qui est proposé. `Occurrence` répond à **quand / où**. `Journey` est présenté comme une **démarche**. `Access` est le **droit obtenu**, contextualisé selon le métier.

## Règles de présentation

- L'accueil personnel répond d'abord à « Que dois-je faire maintenant ? » avant d'afficher l'historique.
- Les démarches viennent de `Journey`, jamais de `TicketOrder`.
- Les accès viennent de `Access`, jamais de `Ticket`.
- La date et l'heure viennent de `Occurrence`.
- Le lieu physique vient de `OccurrencePlace → Place`.
- Un QR participant vient d'un `AccessCredential` actif et n'est jamais renouvelé simplement parce que la page est affichée.
- Les états backend sont traduits dans une couche de présentation centralisée ; les templates n'affichent pas les enums anglais.
- Les notes administratives, raisons techniques, identifiants d'acteur, payloads/signatures et informations provider inutiles ne sont pas exposés.

## Vocabulaire contextuel

Le backend garde `Access` générique, mais l'interface l'adapte :

- verticale Event : **Billet**, **Mon billet**, **Billet valide**, **Billet utilisé** ;
- registration : **Confirmation**, **Inscription confirmée** ;
- invitation : **Invitation**, **Invitation acceptée** ;
- reservation : **Réservation**, **Réservation confirmée**.

Le même principe s'applique à `Journey`, présenté comme inscription, réservation, invitation, demande ou achat selon le workflow.

## Paiement

Commerce et Payment n'apparaissent que lorsque la démarche en a besoin :

- `none` : aucun bloc de paiement et aucun faux `Payment` ;
- `upfront` : paiement en ligne requis avant confirmation ;
- `after_approval` : paiement en ligne seulement après validation ;
- `on_site` : **À payer sur place**, jamais « Impayé » ;
- `later` : paiement prévu ultérieurement selon le contexte métier.

La surface participant démarre depuis `CommerceOrder`. Le service `Payment` reste propriétaire du provider et de l'idempotence. Pour les achats Event encore projetés vers `TicketOrder`, l'adaptateur de paiement conserve temporairement ce bridge parce que l'émission Event actuelle passe encore par le service de confirmation TicketOrder. Ce bridge pourra disparaître lorsque l'émission Event sera déclenchée directement depuis Commerce/Access sans consommateur `TicketOrder`.

## Event n'est pas obligatoire

La Participant Experience doit fonctionner pour une Activity sans aucune verticale Event :

```text
Activity
  ↓
Occurrence
  ↓
Journey registration
  ↓
Access
```

Ce scénario n'utilise aucun `Event`, `Ticket` ou `TicketOrder`. Il constitue le test architectural principal de cette couche produit.

Lorsqu'un Event existe, il fournit seulement le contexte et le vocabulaire événementiels. Les données restent issues des propriétaires canoniques : Activity, Occurrence, Offer/Capacity, Journey, Commerce/Payment et Access.

## Ownership et confidentialité

Les selectors participant sont strictement personnels :

- une démarche est visible par son bénéficiaire dans l'espace participant ;
- un accès est visible par son bénéficiaire ;
- une commande Commerce participant est visible par son acheteur ;
- initier une démarche pour une autre personne ne donne pas accès à l'espace personnel de cette personne ;
- les changements d'UUID vers un objet appartenant à un autre participant répondent selon le contrat serveur sans élargir les permissions.

Les données financières internes du bénéficiaire du paiement, les données provider et les notes internes restent hors de la présentation participant.

## Navigation et rôles multiples

La navigation personnelle est centrée sur : **Accueil**, **Mes démarches**, **Mes accès**, **Notifications**, **Profil**.

Un Profil qui possède aussi des Mandats professionnels reste la même personne. Ses outils d'organisation sont affichés dans une section contextuelle séparée et il peut toujours revenir à **Mon espace**. La Participant Experience ne transforme jamais « organisateur » en identité globale.

## Notifications

Notifications reste son propre domaine. Les notifications liées à une `Journey`, un `Access` ou une `CommerceOrder` ouvrent en priorité la page participant canonique correspondante. Les anciens `action_url` restent seulement un fallback pour les notifications sans relation canonique exploitable.

## Compatibilités Events encore conservées

Les anciennes surfaces `Ticket`, `TicketOrder`, Waitlist, Transfer et certains callbacks Event ne sont pas la source de la nouvelle Participant Experience. Elles restent uniquement parce que des consommateurs actuels existent encore : émission Event après paiement, transfert de billets, waitlist, scanner/analytics et certains parcours professionnels Event.

Aucune nouvelle écriture participant générique ne doit être ajoutée à ces modèles. Leur suppression devient possible au fur et à mesure que ces consommateurs sont migrés vers Commerce/Access et que les tests Event ne dépendent plus de leurs projections.

## Démo et tests

La démo E2E contient des scénarios canoniques déterministes :

- Event payant avec Commerce/Payment et Access ;
- inscription gratuite non-Event sans Payment ;
- réservation `on_site` sans transaction provider ;
- invitation avec acceptation participant et émission d'Access.

Les tests couvrent en priorité selectors, présentation, ownership, pages Journey/Access, QR AccessCredential, paiement Commerce, gratuit, on-site, invitation, notifications, mobile et le scénario sans Event/Ticket/TicketOrder.

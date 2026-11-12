# Journal des versions

## 0.1.3 — 12 novembre 2026
- Décocher un dossier qu'on avait coché en entier depuis un choix partiel rend ce choix, au lieu de tout décocher. « tout décocher », à côté du compte, vide le dossier d'un clic.

## 0.1.2 — 12 novembre 2026
- La case d'un dossier montre ce qui est coché en dessous : pleine quand tout l'est, barrée d'un trait quand une partie seulement de ses sous-dossiers l'est (avec le compte à côté). Cliquer une case barrée coche tout le dossier.
- Le bilan liste les fichiers qu'Immich ne connaît pas (ils restent dans le dossier).
- Corrigé : le nombre de fichiers inconnus affiché à la racine oubliait ceux posés directement à la racine.

## 0.1.1 — 12 novembre 2026
- Icône de l'appli : une montagne et le chemin du troupeau.
- Inventaire : le parcours du dossier des photos ne s'arrête plus sur un dossier illisible et n'entre plus dans les dossiers techniques du NAS ; l'inventaire d'Immich est enregistré avant ce parcours.
- `pc/immich-ml.yml` : la reconnaissance d'Immich sur le PC pendant la migration.

## 0.1.0 — 12 novembre 2026
Première version, **jamais essayée sur un vrai Immich** : elle sert d'abord à l'essai sur un petit dossier.
- Arborescence de la bibliothèque externe, cases à cocher, nom d'album proposé et modifiable par dossier.
- Passage d'un lot : envoi, contrôle de la copie (empreinte), report des albums, tags, description, date corrigée,
  photos animées, visages (reconnus seuls, rattachés, ou recréés). Rejouable ; ne supprime rien.
- Bilan par dossier ou par année, écarts dits en clair, échantillon à ouvrir dans Immich.
- Suppression des originaux sur un clic, pour les seules photos prouvées copiées ; retour arrière tant que les originaux sont là.
- `correspondance.csv` et `instantanes.jsonl` écrits dans le dossier de données.
- Mot de passe commun obligatoire, mode lecture seule, dossiers exclus.
- Tests : 15 contre un faux Immich, 3 d'écran.

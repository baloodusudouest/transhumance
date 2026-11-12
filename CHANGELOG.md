# Journal des versions

## 0.1.7 — 12 novembre 2026
- **Après la suppression, le dossier est rangé.** Le bilan dit « Terminé » au lieu de « Pas encore supprimable ». Un dossier dont tous les originaux sont supprimés quitte l'arbre (un lien « Afficher » le remontre) et n'est plus compté dans « Faire passer les dossiers cochés ». Un dossier où il reste des fichiers inconnus d'Immich reste visible.

## 0.1.6 — 12 novembre 2026
- **Correction** : « Immich a refusé le rattachement d'un visage (400) ». Transhumance inversait la personne et le visage dans la demande ; vérifié dans le code d'Immich. Le faux Immich des tests se comporte maintenant comme le vrai sur ce point.
- Un visage qu'Immich refuse de rattacher ne coupe plus le lot : la photo part en écart, les autres continuent.

## 0.1.5 — 12 novembre 2026
- **Reconnaissance d'Immich : le PC ou le NAS ?** Dans Connexion, une tuile liste les adresses qu'Immich essaie dans l'ordre, dit laquelle répond (donc laquelle travaille), et montre ce qui attend dans les files : visages, personnes, recherche intelligente, texte (OCR), doublons. Une ligne le résume sur l'écran Migrer. Relu toutes les dix secondes, en lecture seule.

## 0.1.4 — 12 novembre 2026
- Le bilan distingue les photos « envoyées, pas encore contrôlées » de celles « pas encore envoyées » : pendant un lot, il ne laisse plus croire que rien n'est passé.
- Le compteur repart de zéro pour le contrôle, au lieu de rester sur le total de l'envoi.
- iPhone : le bouton « Défaire ce dossier » ne dépasse plus du cadre.

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

# Journal des versions


## 0.4.0 — 14/11/2026

- **Passage automatique des dossiers demandés par Millésime** (case dans « Migrer », coupée par défaut). Dès qu'un dossier est entièrement daté dans Millésime, sa demande arrive ici ; avec la case cochée, Transhumance le fait passer tout seul (envoi et contrôle, comme « Faire passer »), un dossier à la fois, quand aucun lot ne tourne (regard chaque minute). Les originaux ne sont jamais supprimés sans clic, après le bilan. Pas assez de place : la demande est marquée et reste à faire à la main.

## 0.3.1 — 13 novembre 2026
- **Toujours sombre.** Le thème clair est retiré : l'appli est sombre partout, ouverte seule comme dans l'Anneau, quel que soit le réglage du téléphone.

## 0.3.0 — 13 novembre 2026
- **Demande de passage par une autre appli.** Millésime peut signaler qu'un dossier est entièrement daté (`POST /externe/demandes`, jeton `TRANSHUMANCE_JETON_MILLESIME` ; sans jeton, l'adresse est fermée). Transhumance le note au journal et l'affiche dans l'arbre (« demandé par Millésime »). Il ne coche rien et ne lance rien : c'est toujours toi qui fais passer. La demande tombe d'elle-même quand le dossier n'a plus rien à envoyer.
- Refusé : un dossier hors de la bibliothèque externe, inconnu de Transhumance, ou de ceux qui ne sont jamais migrés.
- Tests : 24 du serveur.

## 0.2.1 — 13 novembre 2026
- **« Lot interrompu : Immich a refusé le report d'un tag (500) ».** Un tag, une description ou une note qu'Immich refuse à l'envoi n'arrête plus le lot : l'envoi continue, et le contrôle reprend le report.
- **Le contrôle répare ce qu'un lot coupé a laissé.** Avant de juger une copie, il lui remet ce qui manque : tags, description, note, favori, albums de l'ancienne photo. Une photo envoyée juste avant une interruption n'est donc plus déclarée « prête » sans ses tags.
- Deux écarts nouveaux, non bloquants, quand Immich refuse encore au contrôle : « tag » et « description ». Tant qu'ils ne sont pas acceptés, le dossier n'est pas supprimable.
- Tests : 23 du serveur.

## 0.2.0 — 13 novembre 2026
- **Connexion commune.** Connecté à l'Anneau, on n'a plus à se connecter ici : l'appli accepte le cookie « maison_session » que l'Anneau pose, quand elle est servie par la même adresse que lui. Le cookie est signé avec le mot de passe commun : une appli qui a un autre mot de passe continue de demander le sien. Il vaut trente jours, ou jusqu'au changement du mot de passe ; « Se déconnecter » le retire du navigateur.

## 0.1.8 — 13 novembre 2026
- **Une barre pendant la suppression des originaux** : elle se remplit photo par photo (« 412 sur 2006 »), puis annonce le retrait des anciennes photos d'Immich. Deux suppressions ne peuvent plus tourner en même temps.

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

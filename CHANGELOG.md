# Journal des versions

## 0.9.2 — 20 novembre 2026 (socle 0.11.1)
- Copies communes du socle 0.11.1 : sur une fiche « Connexion », le titre devient « Pour le relier » quand le réglage se fait dans Réglages de l'appli (et non dans la stack).
- **Jamais essayé sur la vraie installation.**

## 0.9.1 — 20 novembre 2026 (identifiant commun de la reconnaissance)
- La fiche « PC de calcul (reconnaissance d'Immich) » prend l'identifiant commun **`immich-ml`** (celui de Chambre noire 0.9.0 pour le même service) au lieu de `pc-calcul`, réservé au calculateur de Millésime et au PC de calcul de Scriptorium. Nom affiché et guide inchangés. Route de l'Anneau : `POST /api/maison/services/immich-ml/verifier`.
- Tests : `tests/test_fiches_connexion.py` suit le nouvel identifiant.
- **Jamais essayé sur la vraie installation.**

## 0.9.0 — 20 novembre 2026 (fiches « Connexion » communes, contrat 3)
- L'écran « Connexion » passe à l'écran commun des applis maison (socle 0.11.0, `$lib/services/`) : deux fiches dépliées, **Immich** et **PC de calcul (reconnaissance d'Immich)**. « Vérifier » ne teste que son service ; l'âge du dernier essai est affiché. Textes « lu » et « écrit » repris de l'ancien écran.
- Serveur : registre `SERVICES` (`maison.Services`) et `GET /api/maison/services`, `POST /api/maison/services/{id}/verifier` (session ou `ANNEAU_CLE`, au plus un essai toutes les 30 s, rien d'écrit, permis en lecture seule). La fiche « État » de l'Anneau les lit.
  - `immich` : essai = version et place libre (`GET /server/version`, `GET /server/storage`). Aucun geste : « Migrer » et « Supprimer » restent dans l'écran Migrer.
  - `pc-calcul` : essai = la lecture de la reconnaissance (réglages d'apprentissage d'Immich, files, un `/ping` de chaque adresse ; ne réveille pas le PC). Voyant vert seulement si le PC fait la reconnaissance (comme l'ancien point). **Guide** : réglages lus (adresses déclarées dans Immich et leur état, files de reconnaissance, tirés du dernier essai), Allumer normalement, En cas de problème (commandes PowerShell), Installation (une seule fois). La lecture de l'écran Migrer (`/api/reconnaissance`, toutes les 10 s) sert aussi d'essai ; `/api/connexions` note aussi Immich.
- Le **dossier des photos** n'est pas un service : sa carte passe dans **Réglages** (mêmes textes). Le détail de la reconnaissance (adresses, files) passe dans le guide de la fiche « PC de calcul » ; `Reconnaissance.svelte` ne garde que la ligne courte de Migrer. `pages/Services.svelte` est retiré.
- `maison.py` du socle 0.11.0 (contrat 3). Nouvelle variable facultative `ANNEAU_CLE` (docker-compose.yml).
- `/api/connexions` reste (Réglages y lit le journal et le dossier des photos) : sa partie `immich` n'est plus lue par l'interface, **à retirer en 0.10.0**.
- Aucune route qui écrit n'a changé.
- Tests : `tests/test_fiches_connexion.py` (forme du contrat 3, accès, Vérifier sans écriture en lecture seule, guide du PC, lecture de Migrer comme essai) ; contrat 3 et socle 0.11.0 dans `test_passage.py` et `test_sante.py` ; tests d'écran 4 et 5 adaptés au nouvel écran. 57 tests serveur et 7 tests d'écran passent.
- **Jamais essayé sur la vraie installation.** Le guide du PC reprend l'en-tête de `pc/immich-ml.yml` (Docker Desktop, conteneur `immich_ml_pc`, port 3003, adresse au-dessus de celle du NAS dans Immich) ; ses commandes PowerShell (pare-feu, `Test-NetConnection`) n'ont jamais été essayées.

## 0.8.0 — 18 novembre 2026 (santé des tâches de fond)
- **Tâches suivies dans `/health`** (champ `taches`, socle 0.9.1) : `passage-auto` (régulière, 60 s : la boucle qui regarde chaque minute s'il y a une demande de Millésime à faire passer), `lot` (à la demande : un passage, par « Migrer » ou par une demande passée toute seule), `inventaire` (à la demande : « Relire » Immich et le dossier des photos), `copie-des-bases` (régulière, 86 400 s).
- Le tour de la boucle automatique est le choix de la demande (rapide) ; le passage lui-même est suivi à part comme un `lot`, pour qu'un passage de plusieurs heures ne fasse pas croire à une boucle bloquée (`Transhumance.demande_suivante()` séparée de `passer_demande_suivante()`, qui fait toujours les deux). Un lot interrompu garde son erreur dans la tâche, montrée à l'écran comme avant, et passe le `lot` en « erreur » dans `/health`. Rien d'autre ne change.
- **Copie de la base** chaque nuit à **01:50, heure de Paris** : `transhumance.db` copiée de façon cohérente (API de sauvegarde de SQLite, vérifiée) vers `/data/copies/transhumance-derniere.db`, écrasée chaque nuit (Hyper Backup tient l'historique) ; état dans `/health` (`copie_base`).
- `/health` : champs ajoutés `version_socle`, `taches`, `copie_base` ; rien d'existant ne change. Les messages d'erreur des tâches n'y sont qu'avec le jeton commun (`Authorization: Bearer MAISON_JETON`) ou une session valide.
- `maison.py` du socle 0.9.0. Un seul worker uvicorn (registre en mémoire).
- Jamais essayé sur la vraie installation (ni la copie de nuit, ni sa remise en place).
- Tests : 51 (3 nouveaux, `tests/test_sante.py` ; le test de `/health` de `test_reglages.py` suit les nouveaux champs).

## 0.7.6 — 18 novembre 2026 (constats moyens de l'audit)
- **M32** : « Se déconnecter » vaut encore après un redémarrage : la génération des sessions est gardée dans `/data/session_generation` et relue au démarrage (comme l'Anneau). La page Connexion n'écrivait déjà plus rien dans le dossier des photos depuis la 0.7.1 (`os.access`) ; un test le vérifie maintenant. **Jamais essayé sur la vraie installation.**
- `maison.py` du socle 0.8.2 (audit M3) : réglages secrets reconnus par mots, adresse avec identifiant écartée, champ `ecartes` dans la sauvegarde (noms seulement).

## 0.7.5 — 18 novembre 2026 (cookies Secure)
- **Cookies `Secure` en https** (audit du 17/11/2026, même correctif dans toutes les applis maison) : ouverte en https (directement, derrière Tailscale Serve qui le dit par `X-Forwarded-Proto`, ou d'après l'origine de la page), l'appli pose ses cookies de session avec l'attribut `Secure` : ils ne partent jamais en clair. En http (adresse locale), rien ne change.

## 0.7.4 — 18 novembre 2026 (révocation du cookie commun)
- **« Se déconnecter » dans l'Anneau ferme vraiment la connexion commune** (audit du 17/11/2026, même correctif dans toutes les applis maison) : le cookie commun `maison_session` porte maintenant la génération tenue par l'Anneau (« génération.expiration.signature ») ; « Se déconnecter » l'augmente, et chaque appli la lit dans l'annuaire de l'Anneau (`/externe/services`, au plus une minute de retard) : un cookie commun d'avant la déconnexion ne vaut plus nulle part. Si l'Anneau ne répond pas, le cookie reste accepté comme avant (rien ne se bloque). **Toutes les applis doivent être à jour ensemble** ; une seule reconnexion est demandée après la mise à jour.
- Module commun `maison.py` (socle 0.8.0) : `generation_commune()`, `definir_generation_commune()` ; l'annuaire lit aussi `generation_commune` (une ancienne réponse de l'Anneau, liste seule, reste lue).

## 0.7.3 — 17 novembre 2026 (corrections de l'audit, suite)
- Un fichier refusé par Immich à l'envoi (abîmé, format refusé) ne bloque plus tout le lot à chaque relance : il passe en écart bloquant « refusé » et reste en place ; les fichiers suivants partent. Immich injoignable ou clé refusée arrêtent toujours le lot.

## 0.7.2 — 17 novembre 2026 (connexion plus sûre)
- **Connexion plus sûre** (audit du 17/11/2026, même correctif dans toutes les applis maison) :
  - un cookie portant un caractère non ASCII donnait une erreur 500 sur toute l'API ; il est maintenant simplement refusé ;
  - les clés qui signent les cookies (celui de l'appli et le cookie commun `maison_session` posé par l'Anneau) sont tirées du mot de passe par PBKDF2 : un cookie capté sur le réseau local ne permet plus de chercher le mot de passe à grande vitesse. **Toutes les applis doivent être à jour ensemble** ; une seule reconnexion est demandée après la mise à jour ;
  - des essais de mot de passe lancés en parallèle ne contournent plus le délai : au-delà de 30 essais en 5 minutes, tout est refusé sans comparer.
- Module commun `maison.py` (socle 0.7.0) : l'annuaire de l'Anneau est relu 30 s après un échec (avant : 10 min sans adresses après un redémarrage de la stack) ; un réglage `nan` ou infini est refusé ; un `reglages.json` abîmé est mis de côté (`.corrompu`) au lieu d'être écrasé.

## 0.7.1 — 17 novembre 2026 (corrections de l'audit, suppression des originaux)
- **Bug grave** : « Supprimer » sur un dossier dont le nom contient `_` prenait aussi les dossiers voisins (`Voyage_2019` prenait `Voyage 2019`, `VoyageX2019`, `voyage_2019` : `LIKE` traitait `_` comme un joker et ignorait la casse). Le dossier est maintenant choisi par préfixe exact, pour la suppression comme pour la liste des fichiers inconnus.
- Le fichier `.xmp` n'est supprimé avec la photo que s'il est à elle seule (`IMG_1.jpg.xmp`, ou `IMG_1.xmp` sans autre `IMG_1.*` à côté) et si Immich l'a vraiment reçu (pas un doublon).
- Si la suppression s'arrête en route (partage déconnecté, erreur), les anciennes photos déjà supprimées sont quand même retirées d'Immich ; un échec de ce retrait est noté au journal (« Retrait d'Immich à refaire »).
- La partie vidéo d'une photo animée en écart bloque maintenant la suppression de la photo.
- Dernière preuve au clic : la copie doit être dans le stockage d'Immich (ni bibliothèque externe, ni hors ligne) et différente de l'ancienne.
- La page Connexion n'écrit plus de fichier d'essai dans le dossier des photos (même en lecture seule) pour savoir s'il est inscriptible.
- Tests : 3 de plus. **Jamais essayé sur la vraie installation.**

## 0.7.0 — 16 novembre 2026

- **Réglages dans l'appli.** Les dossiers jamais migrés se règlent maintenant dans l'écran Réglages (un dossier de premier niveau par ligne), à côté du passage automatique des demandes de Millésime. Au premier démarrage, Transhumance reprend une fois la valeur de l'ancienne variable `TRANSHUMANCE_EXCLUS` (une ligne au journal) ; ensuite la variable n'est plus lue.
- **Sauvegarde par l'Anneau.** L'Anneau peut lire les réglages chaque nuit (`GET /externe/sauvegarde`, jeton commun seulement ; sans jeton posé, la porte est fermée). Il ne reçoit que les réglages et la version : ni variable, ni chemin, ni clé d'Immich.
- **Restaurer.** Nouvelle tuile dans Réglages : choisir une date, voir ce qui changerait (avant → sauvegardé), confirmer. Seuls les réglages changent, même en lecture seule ; Anneau injoignable ou rien à restaurer : un message, pas d'erreur.
- **Anciens noms retirés.** Le mot de passe vient de `MAISON_PASSWORD` seul (12 caractères au moins ; sans lui, Transhumance ne démarre pas) ; `TRANSHUMANCE_PASSWORD` n'est plus lu. Les demandes de Millésime ne s'ouvrent plus qu'avec `MAISON_JETON` (`TRANSHUMANCE_JETON_MILLESIME` n'est plus lu). L'adresse d'Immich des liens du bilan vient seulement de l'Anneau (`TRANSHUMANCE_IMMICH_ADRESSE` n'est plus lue). `TRANSHUMANCE_LECTURE_SEULE` reste.
- Rien ne change dans le passage des photos, le bilan ni la suppression : mêmes preuves, même lecture seule à deux endroits.
- Tests : 42 du serveur, 7 d'écran.

## 0.6.0 — 16 novembre 2026

- **Variables communes de la maison** (module `app/maison.py`, copié du socle sans retouche). Rien ne change tant que la stack n'a pas les nouvelles variables : chaque ancien nom reste lu en repli.
- **Mot de passe** : `MAISON_PASSWORD`, sinon `TRANSHUMANCE_PASSWORD` comme avant.
- **Lecture seule** : `MAISON_LECTURE_SEULE=oui` met toute la maison en lecture seule, Transhumance compris ; `TRANSHUMANCE_LECTURE_SEULE` (« oui » ou « non ») l'emporte pour cette appli. La garde reste posée deux fois (avant tout travail et au plus près d'Immich). Réglages dit d'où vient la lecture seule : toute la maison ou cette appli.
- **Demandes de Millésime** (`/externe/demandes`) : acceptées avec l'ancien jeton `TRANSHUMANCE_JETON_MILLESIME` ou avec le jeton commun `MAISON_JETON` (et `MAISON_JETON_ANCIEN` pendant un changement). Aucun jeton posé : l'adresse reste fermée.
- **Liens du bilan vers Immich** : l'adresse vient de l'Anneau (tuile « Immich », adresse Tailscale quand la page est ouverte par Tailscale) ; sinon `TRANSHUMANCE_IMMICH_ADRESSE` comme avant.
- Tests : 33 du serveur, 6 d'écran.

## 0.5.0 — 15/11/2026

- **Format commun du socle.** Navigation : rail à gauche sur PC, pilule d'icônes flottante en bas sur iPhone (au lieu de la barre en haut).
- Nouvelle entrée **Réglages** : l'écriture (lecture seule ou non), les dossiers jamais migrés, le journal, la version et la déconnexion. **Connexion** ne garde que les services (Immich, dossier des photos, reconnaissance).


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

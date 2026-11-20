# Reprise — Transhumance

À lire avant de toucher au dépôt. Dossier : `docs/dossier.md` ; avis du conseil : `docs/conseil.md`.

## Où on en est (20/11/2026)

- **0.9.1** (20/11/2026) : la fiche de la reconnaissance d'Immich a l'id commun `immich-ml` (au lieu de `pc-calcul`, réservé au calculateur de Millésime et au PC de Scriptorium). **Jamais essayé sur la vraie installation.**
- **0.9.0** (20/11/2026) : fiches « Connexion » communes (contrat 3, socle 0.11.0). `app/main.py`, section « fiches Connexion » : `SERVICES` = `immich` (essai : version et place libre) et `pc-calcul`, `immich-ml` en 0.9.1 (essai : `Transhumance.reconnaissance()`, guide `_guide_pc` tiré de `ETAT["reconnaissance"]`, aucun appel au GET) ; `maison.monter_services` après la garde. `/api/reconnaissance` et `/api/connexions` notent leurs lectures (`SERVICES.noter`). Écran : `$lib/services/Services.svelte` (commun, ne jamais le retoucher : empreinte testée) ; dossier des photos dans `Reglages.svelte` ; `Reconnaissance.svelte` = ligne courte de Migrer seulement. Partie `immich` de `/api/connexions` à retirer en 0.10.0. Tests : `tests/test_fiches_connexion.py`. **Jamais essayé sur la vraie installation.**
- **0.8.0** (18/11/2026) : santé des tâches de fond (socle 0.9.0). `main.cycle` déclare `TACHE_AUTO` (« passage-auto », régulière `AUTO_S` = 60 s), `TACHE_LOT` (« lot », à la demande) et `TACHE_INVENTAIRE` (« inventaire », à la demande, route `/api/inventaire`) ; lance `maison.planifier_copie("transhumance", [transhumance.db], /data/copies, 01:50 Paris)` (annulée à l'arrêt). `_boucle_auto` : un tour = `Transhumance.demande_suivante()` (nouveau, le choix), puis `_lot_suivi([chemin])` hors du tour ; `_lot_suivi` (aussi pour `/api/migrer`) relance `_LotInterrompu` quand `migrer` a laissé `tache["erreur"]`, avalée ensuite comme avant. `/health` fusionne `maison.sante(request, jeton_commun=maison.jetons(), session_ok=…)`. Suppression et retour arrière non suivis (clics sous les yeux de Julien). Tests : `tests/test_sante.py`. **Jamais essayé sur la vraie installation.**
- **0.7.0** (16/11/2026) : réglages dans l'appli, sauvegarde et restauration ; anciens noms retirés. `app/maison.py` passe au contrat 2 (copié du socle, ne jamais le retoucher : empreinte testée).
  - Réglages d'usage (`app/passage.py`) : `exclus` (liste de dossiers de premier niveau) dans `maison.Reglages(<data>/reglages.json, REGLAGES_DEFAUTS, REGLAGES_VARIABLES)`, repris une fois de `TRANSHUMANCE_EXCLUS` au premier démarrage (ligne « Réglage repris de la stack : exclus » au journal, sans la valeur) ; `auto_demandes` reste dans la table `reglages` de la base (0.4.0). `Transhumance.exclus()`, `reglages_tout()`, `changer_reglages()` (tout vérifié avant d'écrire, une ligne au journal par réglage changé, permis en lecture seule : ni Immich ni le dossier ne sont touchés). `Config.exclus`, `Config.immich_adresse`, `Config.jeton_millesime` retirés (`app/config.py`).
  - Adresses (`app/main.py`) : `GET/PUT /api/reglages` (session ; mauvais type → 400), `GET /externe/sauvegarde` (`maison.sauvegarde("transhumance", …, exclus=EXCLUS_SAUVEGARDE)`), `GET /api/restaurer` (dates, ou différences avec `?le=`), `POST /api/restaurer` (applique les différences). L'Anneau injoignable → 503, rien à restaurer → 404, avec un message.
  - Portes `/externe/…` : `maison.jetons()` seul ; aucun jeton commun posé → 404, mauvais jeton → 401. `TRANSHUMANCE_JETON_MILLESIME` n'ouvre plus rien (testé).
  - Mot de passe : `maison.mot_de_passe()` sans ancien nom ; moins de 12 caractères → refus de démarrer (« MAISON_PASSWORD est absent ou trop court… »).
  - Adresse d'Immich dans le navigateur : `maison.Annuaire` seul ; Anneau injoignable et rien en mémoire → pas de lien dans le bilan (le reste s'affiche).
  - Écran : `Reglages.svelte` — tuiles « Réglages » (dossiers jamais migrés, passage automatique, Enregistrer) et « Restaurer » (date, différences, confirmer). Tests d'écran : `test_5b_reglages_puis_restaurer`, tuile Restaurer ouverte sur iPhone sans débordement ; le serveur de démonstration a un faux Anneau.
  - **Déploiement en deux temps** : d'abord la nouvelle image avec la stack actuelle (les réglages sont repris des anciennes variables au premier démarrage), vérifier Réglages, puis la nouvelle stack sans les anciennes lignes (`TRANSHUMANCE_PASSWORD`, `TRANSHUMANCE_JETON_MILLESIME`, `TRANSHUMANCE_IMMICH_ADRESSE`, `TRANSHUMANCE_EXCLUS`).
  - Attention : Millésime 2.11 envoie encore son ancien jeton de paire en premier tant que `MILLESIME_JETON_TRANSHUMANCE` est posé ; Transhumance 0.7.0 le refuse (401). Les demandes de passage ne passent qu'avec un Millésime qui envoie `MAISON_JETON` (sa version nettoyée), ou une fois sa ligne `MILLESIME_JETON_TRANSHUMANCE` retirée de la stack.
  - **Jamais essayé sur la vraie installation.**
- **0.6.0** (16/11/2026) : variables communes de la maison — `app/maison.py` (contrat 1, copié du socle, ne jamais le retoucher : empreinte testée). `app/config.py` : `maison.mot_de_passe("TRANSHUMANCE_PASSWORD")`, `maison.lecture_seule("TRANSHUMANCE_LECTURE_SEULE")` + `lecture_seule_origine` (montrée dans `Reglages.svelte`). `app/main.py` : `/externe/demandes` accepte `TRANSHUMANCE_JETON_MILLESIME` et `maison.jetons()` (`maison.jeton_valide`) ; `ANNUAIRE` + `arbre_vu` : `immich_adresse` lue dans l'Anneau (tuile « Immich »), repli `TRANSHUMANCE_IMMICH_ADRESSE`. Jamais essayé sur la vraie installation : les nouvelles variables ne sont pas encore dans la stack.
- **0.5.0** (15/11/2026) : format commun — pilule en bas sur iPhone, rail sur PC, page `Reglages.svelte` (écriture, exclus, journal, version, déconnexion) ; `Services.svelte` ne garde que les services. Écart retiré du § 7 de `socle/docs/format.md`.
- **0.3.1** (13/11/2026) : toujours sombre (blocs `prefers-color-scheme: light` retirés, variante `dark:` partout).
- **0.3.0** (13/11/2026) : `/externe/demandes` (jeton de Millésime), `Transhumance.demander`, `demande` sur les nœuds de l'arbre, pastille dans `Migrer.svelte`. Jamais essayé sur la vraie installation.
- **0.2.1** (13/11/2026) : vu sur la vraie migration, « Immich a refusé le report d'un tag (500) » après 194 envois. Cause côté Immich non établie (erreur interne). `_envoyer` n'arrête plus le lot sur un tag ou une description ; `_finir_reports` (appelé par `_controler`) remet tags, description, note, favori, et le contrôle remet les albums manquants. Avant la 0.2.1, le contrôle ne vérifiait ni les tags ni la description : une photo envoyée juste avant une coupure pouvait passer « prête » sans eux.
- **0.2.0** (13/11/2026) : connexion commune avec l'Anneau — cookie `maison_session` (accepté ; `Sessions.connecte`, `commun_valide` dans `app/auth.py`). Jamais essayée sur la vraie installation.
- **0.1.0** : écrite et testée contre un **faux Immich** (`tests/faux_immich.py`), qui se comporte comme on
  suppose qu'Immich se comporte. **Jamais lancée sur le vrai.** Prochaine étape : l'essai sur un petit dossier.
- **0.1.5** : `Transhumance.reconnaissance()` lit `GET /system-config` (machineLearning.urls) et `GET /queues`, et interroge `/ping` de chaque adresse. **Forme de `/system-config` supposée, pas vue sur le vrai Immich** ; la clé doit avoir le droit de lire les réglages.
- Premier lot réel lancé le 12/11 (un dossier d'environ 2000 fichiers) : envoi accepté, contrôle en cours, aucun écart sur les premières photos.
- **0.1.6** : le premier lot réel s'est arrêté au premier rattachement de visage (400). Cause : `PUT /faces/{id}` prend la **personne** dans l'adresse et le visage dans le corps (face.controller.ts). Corrigé ; **le rattachement reste à voir réussir sur le vrai Immich**.
- La sonde (lecture seule) a été faite : résultats dans le projet Claude, pas dans ce dépôt public.

## À vérifier à l'essai sur le vrai Immich (3.4.1)

1. L'envoi d'un fichier déjà présent en externe est-il accepté (et non « doublon ») ?
2. Les visages de la copie sont-ils rattachés seuls à la même personne ? En combien de temps (`FILES`, `_attendre_files`) ?
3. `PUT /assets/copy`, `PUT /faces/{id}`, `POST /faces`, `PUT /tags/{id}/assets`, `DELETE /assets` avec `force` :
   mêmes formes qu'écrites dans `app/immich.py` ?
4. La photo est-elle rangée dans le dossier de son album (le modèle de stockage lit l'album au moment du rangement ;
   sinon relancer la tâche « Migration du modèle de stockage » dans Immich après le lot) ?
5. Que fait Immich quand le fichier d'une photo externe disparaît avant notre retrait ?
6. La recherche `POST /search/metadata` avec `libraryId` renvoie-t-elle aussi les photos masquées et archivées ?

## Ce qu'il ne faut pas casser

- `test_supprimer_ne_supprime_que_ce_qui_est_prouve` fige ce que le clic fait.
- Au moment de supprimer, la copie est relue dans Immich et le fichier re-haché : rien ne part sur la foi d'un bilan ancien.
- Un fichier qu'Immich ne connaît pas n'est jamais touché ; un dossier n'est jamais supprimé.
- Le journal ne contient aucun nom de personne. Le dépôt est public : exemples inventés seulement.
- Lecture seule refusée deux fois : dans `Transhumance.exiger_ecriture` et dans `Immich._garde`.
- Les réglages ne sortent que par `/externe/sauvegarde` : réglages et version seulement (`EXCLUS_SAUVEGARDE` + `maison.est_secret`). Restaurer ne change que les réglages.

## Limites connues

- La vignette d'une personne qui pointait sur une ancienne photo n'est pas repointée.
- Pas de contrôle « aucune personne nouvelle » après un lot.
- Interface pensée pour le PC.

# Reprise — Transhumance

À lire avant de toucher au dépôt. Dossier : `docs/dossier.md` ; avis du conseil : `docs/conseil.md`. 0.10.0 : `docs/dossier-0.10.0.md`, `docs/conseil-0.10.0.md`.

## Où on en est (26/11/2026)

- **0.10.0 (26/11/2026)** : les vidéos restantes (`.wma` qui sont des WMV, `.mov`, `.mp4`, refusées ou inconnues d'Immich) passent en MP4. Détail dans `CHANGELOG.md`.
  - `app/video.py` (partagé avec l'encodeur du PC, sans base ni Immich) : `sonder`, `mesures`, `voie` (remux / tel_quel / encode / pas_video), `date_trouvee`, `nom_mp4`, `commande`, `mettre_en_mp4` (plafond 1,5 ×), `essai_vaapi`, `prouver` (durée, son, images, définition, décodage, SSIM).
  - `app/passage.py` : `preparer_videos` (appelé par `_migrer`), file `prendre` / `vie` / `finir` / `echouer` / `_rendre_perimes`, `encodeur_nas_tour`, `dossiers_a_envoyer`, `etat_encodage`, `_prouver_video` (dans `_controler`), sas `_vers_sas` / `remettre` / `vider_sas`, `_original_inchange` (dans `supprimer`). États `a_encoder` et `encodee`. `RESTENT` = refuse, pas_video, encodage. Clé `videos_lancees` (dossiers dont « Faire passer » a lu les vidéos) dans `reglages` de la base.
  - `app/main.py` : boucle `_boucle_encodeur` (tâche `encodeur-nas`, `ETAT["encodeur_nas"]=False` la coupe dans les tests), envoi automatique des MP4 dans `_boucle_auto`, porte `/calcul/…` (garde : `TRANSHUMANCE_JETON_CALCUL`), `/api/encodage`, `/api/sas/remettre`, fiche `encodeur-pc`. Partie `immich` de `/api/connexions` retirée.
  - `app/encodeur.py` + `Dockerfile.encodeur` + `pc/encodeur.yml` + `pc/encodeur.env.exemple` : l'encodeur du PC.
  - Relecture indépendante du 26/11/2026 : 8 défauts corrigés avant publication (voir `CHANGELOG.md`), dont le sas qui relit la copie dans Immich avant d'effacer et la preuve sur l'empreinte du MP4 envoyé.
  - Déploiement : nouvelle variable `TRANSHUMANCE_JETON_CALCUL` (stack et `.env` du PC) ; ligne `devices: /dev/dri` **seulement si** `ls /dev/dri` sur le NAS montre `renderD128` (sinon le conteneur ne se crée pas).
  - **Jamais essayé sur la vraie installation.**

- **0.9.7 (24/11/2026)** : la taille d'un dossier est ce qui reste sur le NAS. `arbre()` (`app/passage.py`) ajoute `restants` et `poids_restant` à chaque nœud (tout sauf `supprimee`, remonté jusqu'à la racine) ; `photos`/`videos`/`poids` restent le total de départ (`fini`, `avance` de `Migrer.svelte` s'en servent). Écran : `taille(n)` dans `Migrer.svelte`. Test `test_097_…`. Cause : 219,3 Go encore affichés le 24/11 après la suppression de la Pellicule. **Jamais essayé sur la vraie installation.**

- **0.9.6 (23/11/2026)** : un fichier refusé par Immich (écart `refuse`) ne bloque plus le dossier. `RESTENT = {"refuse"}` et `reste_seulement(l)` dans `app/passage.py` ; `bilan()` : `refuses`, `en_attente` sans eux, `termine` = supprimées + refusées, champ `reste` sur l'écart ; `_finis()` compte les dossiers dont il ne reste que des fichiers refusés. `eligible()` (suppression) inchangé : un écart bloquant n'est jamais supprimé. `Migrer.svelte` : ligne de l'écart et message « Pas encore supprimable ». Tests `test_096_…`. Cause : vu le 23/11/2026 sur un vrai dossier. **Jamais essayé sur la vraie installation.**

- **0.9.4 (21/11/2026)** : case d'un dossier vide → pleine → vide. Dossiers finis (tous originaux supprimés) sans case (`_finis()` dans `_cocher`, `arbre`, `a_migrer`). Souvenir de la 0.1.3 retiré. Test `test_094_…`. **Jamais essayé sur la vraie installation.**
- **0.9.3 (21/11/2026)** : rien ne part sans être coché. `POST /api/migrer` exige la liste affichée (`dossiers`) et refuse si elle a changé (409) ; le lot passe cette liste figée. `Transhumance.verrou_lot` : un seul lot à la fois (pris par `/api/migrer` ou `_boucle_auto` avant le choix, passé à `migrer(…, verrou_pris=True)` qui le rend). `/api/dossier` refusé pendant un lot. `demande_suivante` ne prend une demande que si son dossier est coché. `tache` porte `origine` et `dossiers`. Tests `test_093_…`. Cause : bug vu le 21/11 (Pellicule décochée envoyée). **Jamais essayé sur la vraie installation.**
- **0.9.2 (20/11/2026)** : copies communes du socle 0.11.1 (titre « Pour le relier » quand le réglage est dans l'appli).
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

## À vérifier à l'essai (0.10.0)

7. `/dev/dri` existe-t-il sur le DS1520+ ? L'essai de la puce (journal « Puce vidéo du NAS essayée », fiche Connexion) réussit-il avec iHD ou i965 ?
8. Le sas sous `#recycle` est-il bien ignoré par Immich (aucune vidéo du sas réapparue dans la bibliothèque externe après un scan) ?
9. Immich accepte-t-il les MP4 et en fait-il une vignette (`thumbhash`) ? Les dates (balise `creation_time`) sont-elles celles attendues ?
10. Combien de temps prend un réencodage sur le PC (processeur) et sur le NAS ? La preuve (décodage complet + SSIM) sur le NAS est-elle supportable pour les longues vidéos ?

## Ce qu'il ne faut pas casser

- 0.9.3 : rien ne part sans être coché. `test_093_…` figent la liste affichée redonnée par l'écran, le verrou d'un seul lot, et les demandes de Millésime qui attendent la case.
- `test_supprimer_ne_supprime_que_ce_qui_est_prouve` fige ce que le clic fait.
- Au moment de supprimer, la copie est relue dans Immich et le fichier re-haché : rien ne part sur la foi d'un bilan ancien.
- Un fichier qu'Immich ne connaît pas n'est jamais touché ; un dossier n'est jamais supprimé.
- Le journal ne contient aucun nom de personne. Le dépôt est public : exemples inventés seulement.
- Lecture seule refusée deux fois : dans `Transhumance.exiger_ecriture` et dans `Immich._garde`.
- 0.10.0 : un original vidéo ne part qu'au sas (jamais effacé au clic), et seulement si son MP4 est prouvé (durée, son, images, définition, décodage, vignette, SSIM ≥ 0,95) et si l'original a la taille et la date lues à la préparation. `test_passage_complet_des_videos` et `test_une_copie_trop_courte_bloque_la_suppression` le figent.
- 0.10.0 : la file ne donne une vidéo que si son dossier est coché et lancé (`test_rien_ne_part_sans_etre_coche`). Les Live Photos (parties cachées) n'entrent jamais dans la file.
- Les réglages ne sortent que par `/externe/sauvegarde` : réglages et version seulement (`EXCLUS_SAUVEGARDE` + `maison.est_secret`). Restaurer ne change que les réglages.

## Limites connues

- La vignette d'une personne qui pointait sur une ancienne photo n'est pas repointée.
- Pas de contrôle « aucune personne nouvelle » après un lot.
- Interface pensée pour le PC.
## État (22/11/2026) — 0.9.5 : barre d'onglets collée en bas sur iPhone (`App.svelte`, classes du socle 0.12.1 : `fixed inset-x-0 bottom-0 … pb-[calc(0.375rem+env(safe-area-inset-bottom))]`, `md:right-auto md:justify-start`). Jamais essayé sur la vraie installation.


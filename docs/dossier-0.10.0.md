# Transhumance 0.10.0 — les vidéos restantes (dossier)

Grill du 26/11/2026 (le propriétaire). Évolution de Transhumance 0.9.7 (`baloodusudouest/transhumance`), coffre relu le 26/11/2026 (note *Transhumance*, *Reprise*, *homelab yml*, *Machine — PC de calcul*, *Calcul de Millésime*, *Calcul de Scriptorium*). **Rien n'est codé tant que le propriétaire n'a pas dit « go ».**

## 1. Besoin

Une fois les photos passées, il reste dans le dossier des photos des **vidéos** que Transhumance ne fait pas passer :

- des **`.wma` qui sont en fait des vidéos WMV** (mauvaise extension, vieux appareils ou logiciels Windows) ;
- des **`.mov`** et des **`.mp4`**.

Elles tombent dans deux tas, selon le cas :

- **refusées par Immich** à l'envoi (écart `refuse`, 0.9.6) : Immich les connaît dans sa bibliothèque externe, avec parfois des visages, des albums, des tags ;
- **inconnues d'Immich** (inconnus) : sur le disque, mais absentes de la bibliothèque externe. Elles n'ont ni date dans Immich, ni visages, ni album.

Choix du propriétaire :

| Sujet | Choix |
|---|---|
| Quelles vidéos | Toutes les vidéos restantes (refusées et inconnues) passent en MP4. **Après le conseil** : celles déjà en H.264/AAC sont **remuxées** (enveloppe changée, image intacte) ; les autres (WMV…) sont réencodées ; les HDR / 10 bits partent **telles quelles** (avant : tout réencoder) |
| Qualité | **Quasi identique** : MP4, vidéo H.264, son AAC, sans perte visible |
| Où encoder | **Sur le PC s'il est allumé, sinon sur le NAS** |
| Repli NAS | **Puce vidéo Intel du NAS** (Quick Sync, `/dev/dri`) |
| Lien PC ↔ Transhumance | **Comme Millésime** : un conteneur « encodeur » dans Docker Desktop demande du travail, encode, renvoie le MP4 |
| Date d'une vidéo inconnue | **Date enregistrée dans la vidéo, sinon nom du fichier, sinon dossier** |
| Preuve avant suppression | **Durée (à 1 s près), image (Immich a fait la vignette et lit la vidéo), date et album** |
| Original | Sur clic, comme les photos (bilan, puis clic, en redonnant le nombre attendu). **Après le conseil** : l'original vidéo part dans un **sas de 30 jours** sur le NAS, effacé seul ensuite ; une copie figée existe aussi sur le cloud |

Hors périmètre : les photos refusées (pas des vidéos) restent dans le tas `refuse` ; les vrais fichiers audio (un `.wma` sans image) ne sont jamais touchés ; « Photos numérisées » reste hors du passage.

## 2. Technique

### 2.1 Reconnaître une vidéo

- L'extension ne suffit pas (`.wma` = WMV). Chaque candidat passe par **`ffprobe`** : il faut au moins un flux vidéo de durée > 0. Sinon : « pas une vidéo », laissé tel quel, compté à part.
- Candidats : écarts `refuse` de type `VIDEO` ou dont le fichier a une extension `.wma .wmv .asf .mov .mp4 .m4v .avi .3gp .mpg .mpeg .mts .m2ts .mkv`, et inconnus portant ces extensions. Liste dans `VIDEOS_A_ENCODER` (`app/video.py`).
- Une vidéo identifiée reçoit l'état **`a_encoder`**, avec ses mesures : durée, définition, codec d'origine, présence du son, rotation, date trouvée.

### 2.2 Réglages d'encodage (fixes, dans le code)

- PC (processeur) : `libx264 -preset slow -crf 18 -pix_fmt yuv420p`, son `aac 192k` (ou copié s'il est déjà AAC), `-movflags +faststart`.
- NAS (Quick Sync) : `h264_qsv -global_quality 20 -look_ahead 1`, même son. Si `/dev/dri` est absent ou que l'essai `h264_qsv` échoue au démarrage, **le NAS n'encode pas** (pas de repli processeur : choix du propriétaire), la vidéo attend le PC, et l'écran le dit.
- Toujours : métadonnées reprises (`-map_metadata 0`), **date posée dans `creation_time`** (et `com.apple.quicktime.creationdate`), rotation conservée, entrelacé → désentrelacé (`yadif` / `deinterlace_qsv`) seulement si `ffprobe` le signale, cadence d'origine conservée.
- Le MP4 porte le nom d'origine avec l'extension `.mp4` (`VID_0001.wma` → `VID_0001.mp4`) pour le rangement Immich.

### 2.3 Qui encode : file d'attente dans Transhumance

- Table `encodages` : une ligne par vidéo (`rel`, `ancien_id` ou vide si inconnue, `etat` = `a_encoder` / `pris` / `encode` / `envoye` / `erreur`, `par` = `pc` ou `nas`, `pris_le`, `essais`, `erreur`, `mesures` JSON, `date`, `source_date`).
- **PC** : porte `/calcul/…` protégée par un nouveau jeton **`TRANSHUMANCE_JETON_CALCUL`** (même modèle que Millésime et Scriptorium) :
  - `POST /calcul/prendre` → une vidéo (id, nom, taille, mesures, réglages) ou 204 ; elle passe `pris` pour 2 h (au-delà, rendue à la file) ;
  - `GET /calcul/fichier/{id}` → l'original en flux ;
  - `POST /calcul/rendre/{id}` → le MP4 en flux, écrit dans `/data/encodes/` (fichier temporaire puis renommé) ;
  - `POST /calcul/erreur/{id}` → message (3 essais, puis `erreur`, visible à l'écran) ;
  - `POST /calcul/signal` → « je suis là » toutes les 60 s (PC vu, nom de la machine).
- **NAS** : tâche de fond `encodeur-nas` (santé socle 0.9.0) qui ne prend une vidéo **que si le PC n'a pas signalé depuis 10 min**, une seule à la fois, en `nice 19`.
- Le PC et le NAS ne prennent jamais la même vidéo (prise en base sous verrou).
- **Rien ne part sans être coché** (0.9.3) : seules les vidéos des dossiers cochés entrent dans la file ; décocher un dossier retire ses vidéos `a_encoder` de la file (celles `pris` finissent leur encodage, qui est jeté).

### 2.4 Envoi et contrôle

- Le MP4 suit le chemin d'une photo : envoi (`im.envoyer`), album du dossier, puis :
  - **vidéo refusée (connue d'Immich)** : instantané de l'ancienne comme pour une photo (tags, description, note, favori, visibilité, albums, visages) ; report sur la copie ;
  - **vidéo inconnue** : pas d'instantané Immich ; date posée par `PUT /assets/{id}` (`dateTimeOriginal`) si Immich lit une autre date que celle trouvée.
- Date d'une vidéo inconnue, dans l'ordre : `creation_time` du conteneur → nom du fichier (`AAAAMMJJ`, `AAAA-MM-JJ`, `VID_AAAAMMJJ_hhmmss`…) → dossier (Pellicule/année/évènement daté → ce jour ; année seule → 1er juillet de l'année, notée « date approchée »). La source est gardée et montrée dans le bilan.
- **Contrôle avant suppression** (remplace l'empreinte pour ces fichiers ; écarts nouveaux) :
  - `duree` (bloquant) : durée Immich de la copie ≠ durée `ffprobe` de l'original à plus de 1 s ;
  - `illisible` (bloquant) : pas de vignette après la file `thumbnailGeneration`, ou `ffprobe` du MP4 rangé par Immich échoue ;
  - `date` (non bloquant, comme aujourd'hui) ; `album`, `visage`, `tag`, `description` : inchangés ;
  - l'empreinte du **MP4 envoyé** est gardée et comparée à la copie rangée (la copie d'Immich doit être notre MP4).
- Au clic « supprimer » : relecture de la copie dans Immich, re-mesure de la durée de l'original (le fichier n'a pas changé : taille + date de modification identiques à l'inventaire), puis suppression de l'original, de son ancienne entrée Immich s'il en avait une, et du MP4 temporaire de `/data/encodes/`.

### 2.5 Place

- `/data/encodes/` ne garde un MP4 que jusqu'à sa copie contrôlée dans Immich. Une seule vidéo en attente d'envoi par encodeur : le PC ne prend la suivante que si la précédente est envoyée.
- Contrôle de place libre avant chaque prise (NAS et Immich) : il faut 2 × la taille de l'original.

### 2.6 Encodeur du PC

- Image `ghcr.io/baloodusudouest/transhumance:encodeur` (Python + ffmpeg de Debian), fichier `pc/encodeur.yml` + `pc/encodeur.env.exemple` (`TRANSHUMANCE_URL`, `TRANSHUMANCE_JETON_CALCUL`, `THREADS`), `restart: unless-stopped`, `pull_policy: always`, dossier de travail `./travail` (vidé à chaque fin de vidéo).
- La carte AMD n'est pas vue par Docker Desktop : encodage par le processeur (choix assumé, « comme Millésime »).

### 2.7 Image du NAS

- Dockerfile : ajout de `ffmpeg` et des pilotes Intel (`intel-media-va-driver-non-free` de Debian bookworm, `vainfo`) dans l'étape d'exécution.
- Stack : `devices: - /dev/dri:/dev/dri` sur `transhumance`, nouvelle variable `TRANSHUMANCE_JETON_CALCUL`. Sans `/dev/dri`, l'appli démarre et dit « le NAS n'encode pas ».

### 2.8 Nettoyages prévus en 0.10.0

- Partie `immich` de `/api/connexions` retirée (annoncé en 0.9.0).

### 2.9 Fiches « Connexion »

- Nouvelle fiche **`encodeur-pc`** (essai : dernier signal ; guide : installer `pc/encodeur.yml`). La fiche `immich-ml` reste.

## 3. Parcours des clics et des écrans

**Migrer** — chaque dossier montre, en plus des photos : « 3 vidéos à encoder », puis « encodage 1/3 (PC) », « 2 encodées, 1 en erreur ». Le bilan du dossier liste les vidéos : nom d'origine, durée, avant → après (codec, poids), date trouvée et sa source, écarts.

**Migrer › Migrer les dossiers cochés** — inchangé : les photos partent, les vidéos du dossier entrent dans la file et partent une fois encodées. La ligne de tâche dit « 12 photos envoyées, 3 vidéos dans la file d'encodage ».

**Ligne d'état en haut de Migrer** (à côté de la reconnaissance) : « Encodage : PC (BUREAU-JULIEN), 4 en attente » / « PC éteint, le NAS encode (Quick Sync) » / « PC éteint, le NAS ne peut pas encoder : les vidéos attendent ».

**Bilan › Supprimer les originaux** — inchangé (par année, en redonnant le nombre). Les vidéos prouvées comptent dans le nombre ; une vidéo en écart bloquant reste et est listée.

**Réglages** — rien de nouveau à régler (réglages d'encodage fixes). **Connexion** — fiche « Encodeur du PC ».

**Vrais sons** (`.wma` sans image) : ligne « 2 fichiers son, laissés tels quels » dans le bilan du dossier, sans case.

## 4. Design

Inchangé (vert mousse `#8fae6b`, sombre, format commun du socle). Les vidéos réutilisent les lignes et pastilles existantes ; une pastille « à encoder » (contour), « encodage » (animée sobrement), « encodée » (pleine).

## 5. Schéma de données

- `photos` : nouveaux états `a_encoder`, `encodee` ; colonne `encodage` (id dans `encodages`, vide sinon). Les vidéos **inconnues** reçoivent une ligne `photos` avec `ancien_id = 'inconnu:' || rel` au moment où elles sont cochées (elles sortent alors de la table `inconnus`).
- `encodages` : voir 2.3.
- `reglages` (base) : `pc_vu` (date, machine).
- Pas de changement de `reglages.json` (rien à sauvegarder par l'Anneau).
- Migration de base au démarrage (colonnes et table ajoutées, rien de supprimé).

## 6. Plan d'implémentation (étapes livrables et testées)

1. **Reconnaître** : `app/video.py` (`ffprobe`, liste des candidats, date trouvée), état `a_encoder`, comptes dans l'arbre et le bilan. Tests avec de petites vidéos fabriquées par ffmpeg dans les tests (un WMV renommé `.wma`, un `.mov`, un vrai son `.wma`).
2. **File et encodeur NAS** : table `encodages`, tâche `encodeur-nas`, essai Quick Sync au démarrage, Dockerfile, stack. Tests : file, verrou, « PC vu » qui arrête le NAS, décochage.
3. **Porte `/calcul` et encodeur du PC** : routes, jeton, `pc/encodeur.yml`, image `:encodeur` dans la CI. Tests contre un faux PC.
4. **Envoi, contrôle et suppression** des vidéos encodées (écarts `duree`, `illisible`), faux Immich étendu (durée, vignette). Le test qui fige la suppression est étendu, jamais affaibli.
5. **Écran** (Migrer, bilan, fiche Connexion) et tests d'écran.
6. **Essai réel** sur un seul dossier avec 2 ou 3 vidéos (un `.wma`, un `.mov`, un `.mp4`), PC allumé puis éteint.

## Décisions prises après le conseil (26/11/2026)

Avis complet : `transhumance-0.10.0-conseil.md`. Ces décisions remplacent le texte ci-dessus là où il diffère.

1. **Trois voies selon ffprobe** :
   - **remux** : vidéo H.264 (8 bits) + son AAC/absent → `-c copy` dans un MP4 (`-movflags +faststart`), sans perte. Fait sur le NAS (pas besoin du PC) ;
   - **tel quel** : HDR (`color_transfer` smpte2084 / arib-std-b67), 10 bits (`pix_fmt` *10*), Dolby Vision, ou HEVC déjà accepté par Immich → envoyé sans transformation, preuve par **empreinte** comme une photo. Si Immich le refuse, il reste dans le dossier (écart `refuse`, comme aujourd'hui) ;
   - **réencodage** : tout le reste (WMV mal nommés `.wma`, MPEG-4 Part 2, MJPEG, etc.) → H.264 CRF 18 sur le PC, Quick Sync sur le NAS.
2. **Live Photos** : un `.mov` dont l'ancienne entrée est `livePhotoVideoId` d'une photo n'entre jamais dans la file ; il suit sa photo comme aujourd'hui.
3. **Preuve renforcée, en bloquant** (remux et réencodage) : durée ±1 s ; son présent si l'original en avait (durée ±1 s) ; nombre d'images ±1 % ; définition et rotation identiques ; décodage complet de la copie rangée par Immich (`ffmpeg -v error -f null -`) ; **SSIM ≥ 0,95** sur 5 instants (10, 30, 50, 70, 90 %) entre l'original et la copie ; empreinte du MP4 produit = empreinte de la copie dans Immich. Nouveaux écarts : `duree`, `son`, `images`, `definition`, `illisible`, `fidelite`. Pour les fichiers encodés, l'écart `empreinte` est remplacé par ces contrôles (nouvel état, jamais contourné).
4. **Sas de 30 jours** : au clic, l'original vidéo est **déplacé** dans `/photos/#transhumance-sas/AAAA-MM-JJ/<chemin d'origine>` (même volume, pas de copie), effacé par la tâche « vider-sas » 30 jours après. Écran Bilan : nombre et poids en sas, date d'effacement ; bouton « remettre » par vidéo tant qu'elle est dans le sas. Le sas est dans `IGNORES` (jamais inventorié).
5. **Ancienne entrée Immich** (vidéo refusée connue d'Immich) : retirée seulement après le contrôle du report (visages, albums, tags) ; le retrait se fait au clic, comme pour les photos.
6. **Champ `origine`** (`externe` / `inconnu`) dans `photos` au lieu d'un préfixe dans `ancien_id` ; décocher un dossier remet ses vidéos inconnues dans `inconnus`.
7. **Nom** : `VID_0001.wma` → `VID_0001.mp4` ; si ce nom existe déjà dans le dossier ou dans Immich, `VID_0001 (transhumance).mp4`.
8. **Date** : le MP4 reçoit la date trouvée dans ses balises (`creation_time`, `com.apple.quicktime.creationdate`) **et** comme date de modification (`os.utime`) avant l'envoi ; balises QuickTime utiles (GPS, appareil) recopiées en plus de `-map_metadata 0`. SHA-1 calculé en flux pour les grosses vidéos.
9. **Plafond** : réencodé > 1,5 × l'original → nouvel essai en CRF 22 ; encore au-dessus → écart non bloquant « grossi » affiché, envoi quand même (la preuve décide de la suppression).
10. **Bail du PC** : signal de vie toutes les 60 s pendant l'encodage (`POST /calcul/vie/{id}` avec l'avancement) ; sans signal pendant 10 min, la vidéo revient dans la file. Un transfert coupé est repris de zéro (fichier temporaire jeté).
11. **Quick Sync** : essai réel au démarrage (2 s de `h264_qsv` sur une mire) ; paquet `intel-media-va-driver` (libre) + `LIBVA_DRIVER_NAME=iHD`. Sous DSM, si `/dev/dri` manque, une tâche planifiée au démarrage du NAS (`modprobe i915`) est documentée dans le coffre ; sans elle, le NAS ne fait que les remux.
12. **Ordre du plan revu** : 0) essai Quick Sync réel sur le NAS (avant tout code de la file NAS) et comptage des vidéos restantes par voie (remux / tel quel / réencodage) et par poids ; 1) reconnaître et classer ; 2) remux et tel quel (sur le NAS, sans PC) avec la preuve renforcée et le sas ; 3) porte `/calcul` et encodeur du PC ; 4) encodeur NAS Quick Sync ; 5) écran ; 6) essai réel sur un dossier, et **restauration de 2 ou 3 vidéos depuis la copie cloud** vérifiée par le propriétaire avant le premier clic de suppression.

Idées notées pour plus tard (hors 0.10.0) : moteur de calcul commun dans `socle` ; réveil du PC par Home Assistant (Wake-on-LAN) quand la file attend.

## Questions pour le conseil (posées le 26/11/2026)

1. Réencoder **toutes** les vidéos restantes (choix du propriétaire) plutôt que seulement celles qu'Immich refuse : quels risques (perte de qualité, métadonnées, vidéos de l'iPhone en HEVC/HDR) et quelles protections ajouter ?
2. Preuve avant suppression sans empreinte : durée + vignette + lecture + date suffisent-elles ? Que manque-t-il (son présent, nombre d'images, définition) ?
3. Quick Sync sur le DS1520+ (J4125) dans un conteneur : pièges connus (pilote `iHD`, droits sur `/dev/dri`, conteneur qui tourne en root) ?
4. Vidéos inconnues : passer par une ligne `photos` « inconnu:… » ou garder un chemin à part ?
5. Taille : un WMV de 2005 réencodé en CRF 18 peut grossir. Faut-il un plafond ?

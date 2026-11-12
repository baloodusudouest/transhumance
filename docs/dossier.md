# Dossier de Transhumance — faire passer la bibliothèque externe dans le stockage d'Immich

Écrit le 12/11/2026 à partir du grill (trois tours). Rien n'est codé.

## 1. Besoin

Aujourd'hui Immich lit les photos là où elles sont : le dossier de Synology Photos, déclaré comme bibliothèque externe (Pellicule, Albums, Pense bête, et le reste). Le but : que ces photos deviennent des photos « à lui », rangées dans son stockage, pour que l'iPhone envoie ensuite directement dans Immich et que la bibliothèque externe disparaisse.

Décidé au grill :

- **Tout migrer** : Pellicule, Albums, Pense bête et le reste. La vérification des dates est finie. Les scans ne sont pas concernés (déjà dans le stockage d'Immich).
- **Une appli au format commun**, pas un script : on y voit l'arborescence des dossiers, on coche ceux à migrer, chacun avec le nom d'album proposé, modifiable.
- **Albums proposés** : Pellicule → un album par dossier d'évènement (« 2024-05-01 Anniversaire ») ; un dossier qui n'a qu'une date est proposé sans album. Albums → « Parent – Enfant » pour un sous-dossier.
- **Les personnes restent les mêmes.** carnet, Treemich et Millésime tiennent par l'identifiant des personnes d'Immich.
- **Les originaux sont supprimés**, dossier par dossier, **sur un clic donné après le bilan**. Une sauvegarde récente hors du NAS existe.
- Après : l'iPhone envoie par l'appli Immich ; la bibliothèque externe est retirée à la fin.

Ce qui rend l'outil particulier : il ne sert qu'une fois, sur toute la photothèque, et sa dernière étape ne se rattrape pas. Une photo qui passe mal ne se voit pas le jour même.

## 2. Technique

**Le fait de départ.** Immich ne sait pas « adopter » une photo externe. Il faut l'envoyer comme une photo neuve (nouvel identifiant), puis reporter dessus tout ce que l'ancienne portait, puis retirer l'ancienne.

**Le passage d'une photo, en six temps :**

1. **Lire l'ancienne** : identifiant, chemin, empreinte, date, favori, description, note, albums, tags, pile, visages (cadre et personne).
2. **Envoyer** le fichier d'origine à Immich (`POST /assets`), avec sa date. Immich la range selon son modèle de stockage. S'il existe un fichier d'accompagnement (`.xmp`), il part avec.
3. **Contrôler la copie** : l'empreinte que renvoie Immich doit être celle du fichier d'origine ; même date de prise de vue ; même type.
4. **Reporter** : albums, favori, pile, liens partagés par l'adresse d'Immich prévue pour cela (`PUT /assets/copy`) ; tags, description, note par l'API ; ajout à l'album du dossier.
5. **Les visages.** Immich détecte et reconnaît les visages de la nouvelle photo. Comme c'est la même image, il les rattache de lui-même aux mêmes personnes — à condition que l'ancienne photo soit encore là. L'outil attend la fin de la reconnaissance, puis compare visage par visage (par recouvrement des cadres) :
   - même personne : rien à faire ;
   - visage détecté mais pas rattaché, ou rattaché ailleurs : il est réaffecté à la bonne personne ;
   - visage que l'ancienne photo avait et que la détection ne retrouve pas (posé à la main) : il est recréé à la main (`POST /faces`).
   Si la photo qui sert de visage à une personne est migrée, la vignette de la personne est repointée sur la nouvelle.
6. **Bilan du dossier**, puis, sur un clic : suppression des fichiers d'origine et retrait des anciennes photos d'Immich.

**L'ordre compte** : l'ancienne photo n'est retirée qu'après le rattachement des visages, sinon une personne dont toutes les photos sont externes disparaîtrait avec elles, et ses liens avec.

**Pile.** FastAPI + SQLite (journal de chaque photo : où elle en est, ses contrôles), interface Svelte du socle. Dans la stack : le dossier des photos monté en écriture (pour la suppression), une clé d'API Immich dédiée. Mot de passe commun obligatoire. Mode lecture seule : l'appli montre l'arbre et ce qu'elle ferait, n'envoie rien, ne supprime rien. Watchtower coupé. Appli retirée de la stack à la fin.

**À vérifier sur le vrai Immich (3.4.1) avant de coder le reste**, par une sonde qui ne fait que lire, puis par l'essai d'une seule photo :
- les adresses ci-dessus répondent comme attendu en 3.4 (l'API a changé en v3) ;
- la reconnaissance rattache bien seule les visages de la copie à la même personne, et en combien de temps ;
- comment Immich traite le retrait d'une photo de bibliothèque externe (corbeille ? fichier supprimé ?) ;
- la place libre, le nombre de photos par bibliothèque, les vidéos, les photos animées, les fichiers d'accompagnement.

## 3. Parcours des clics et des écrans

Quatre entrées, rail à gauche sur PC, pilule sur iPhone (mais l'outil se pilote surtout au PC).

**Migrer** (écran d'ouverture) — l'arborescence. Chaque dossier : nombre de photos et de vidéos, poids, état (à migrer, en cours, copié et contrôlé, originaux supprimés), case à cocher, nom d'album proposé dans un champ modifiable (vide = pas d'album). Cocher un dossier parent coche ses enfants. En haut : place libre, et « Migrer les dossiers cochés ». Un dossier ouvert montre son bilan.

**À traiter** — des tuiles : dossiers prêts à supprimer (bilan tout vert) ; photos dont un contrôle a échoué (empreinte, date, visage non retrouvé, album) ; fichiers qu'Immich ne connaît pas (présents dans le dossier, absents d'Immich) ; photos d'Immich dont le fichier manque ; doublons refusés par Immich (la photo existe déjà dans le stockage).

**Bilan d'un dossier**, avant suppression : photos envoyées / contrôlées ; visages : tant reconnus seuls, tant réaffectés, tant recréés, tant perdus ; albums, favoris, tags reportés ; liste des écarts, chacun avec sa photo. Le bouton « Supprimer les originaux de ce dossier » n'est actif que sans écart, ou après que chaque écart a été accepté un par un.

**Connexion** — Immich (version, clé, droits de la clé, file d'attente des tâches) et le dossier des photos (lisible, inscriptible, place libre). **Réglages** — règles de nom d'album, taille des lots, journal, version, déconnexion.

## 4. Design

Format commun. **Couleur : vert mousse** (sombre `#8fae6b`, clair `#4e6b2f`). Signature : l'arbre des dossiers, avec un trait de couleur qui descend le long de ce qui est passé — on voit le troupeau avancer.

## 5. Schéma de données

```
photos      ancien_id (clé), chemin, empreinte, dossier, etat (vue|envoyee|controlee|reportee|visages|prete|supprimee|ecart),
            nouveau_id, ecarts (liste), le
visages     ancien_id photo, cadre, personne, issue (seul|reaffecte|recree|perdu)
dossiers    chemin (clé), album (nom choisi), coche, etat, bilan
journal     le, quoi (envoi, report, suppression…), ancien_id, nouveau_id
```

Le journal garde la correspondance ancien identifiant → nouvel identifiant de chaque photo : Millésime et carnet en auront besoin pour ce qu'ils ont rangé par identifiant de photo.

## 6. Plan d'implémentation

1. **Sonde** (lecture seule) : ce que contient vraiment Immich, et les réponses de l'API 3.4. Rapport sans nom de personne.
2. **Essai d'une photo**, choisie par l'utilisateur, sans suppression : envoi, contrôle, report, visages. On regarde le résultat dans Immich, carnet et Treemich.
3. **L'appli** : arbre, sélection, noms d'albums, passage par dossier, bilan. Toujours sans suppression.
4. **Un petit dossier en vrai**, bilan, puis première suppression.
5. Le reste, dossier par dossier ou année par année.
6. Fin : retrait de la bibliothèque externe, mise à jour de ce que Millésime et carnet gardent par identifiant de photo, retrait de Transhumance de la stack, `homelab.yml`.

Tests : faux Immich (envoi, visages, albums, refus), dossier de photos inventé ; un test fige ce que « Supprimer » supprime, et prouve qu'il ne supprime rien quand un contrôle manque.

## Décisions prises après le conseil (12/11/2026)

Avis complet : `conseil.md`. Ce qui change par rapport au texte ci-dessus :

- **Les originaux sont supprimés au clic**, comme décidé au grill (le conseil préférait un déplacement) : une copie figée de la photothèque existe déjà sur le cloud. Seuls les fichiers prouvés copiés sont supprimés, jamais un dossier entier ; les fichiers qu'Immich ne connaît pas restent en place et sont listés.
- **Bilan et clic par année** ; le détail par dossier reste consultable. « Défaire » possible tant que les originaux sont là.
- **L'essai iPhone est sans objet** : l'iPhone envoie déjà directement dans Immich et sa pellicule a été vidée.
- **Instantané complet** de chaque ancienne photo (visages, albums, date et lieu corrigés, visibilité, favori, note, tags, pile) et **table ancien → nouvel identifiant**, écrits dans un fichier gardé hors de l'appli.
- **Contrôles** par photo, par dossier et par personne (même nombre de photos par personne, aucune personne nouvelle) ; empreinte calculée par l'appli sur le fichier ; photos animées, archivé / masqué / verrouillé, fuseau, vidéos, chemin final après rangement.
- **Essai sur un lot varié**, pas sur une photo.
- **Tout arrêter pendant un lot** : carnet, Millésime, Treemich, tâches de nuit et scan d'Immich. Immich figé en 3.4.1.
- **Interface allégée** : arbre, cases, noms d'albums, bilan, Connexion. Pas d'écran Réglages, pas de pilule iPhone.
- **Sonde par le navigateur** (lecture seule) avant toute ligne d'appli.

## Questions ouvertes pour le conseil

1. **Supprimer par l'appli ou par Immich ?** L'appli supprime le fichier puis demande à Immich d'oublier l'ancienne photo ; ou bien elle demande à Immich de supprimer la photo externe et vérifie que le fichier a disparu. Lequel laisse le moins de place à un état bancal ?
2. **Faut-il une corbeille maison** (fichiers déplacés dans un dossier « passés » plutôt que supprimés), alors qu'une sauvegarde hors du NAS existe et que l'utilisateur a choisi la suppression ?
3. **Visages perdus** : un visage que la détection ne retrouve pas et qu'on recrée à la main n'a pas d'empreinte de reconnaissance. Est-ce acceptable, ou faut-il bloquer la suppression du dossier ?
4. **Millésime, carnet, Treemich pendant la migration** : faut-il les arrêter (ils écrivent dans Immich la nuit) ?
5. **Que manque-t-il au contrôle** avant suppression ? (vidéos, photos animées, photos archivées ou masquées, photos partagées avec un autre compte.)

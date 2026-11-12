# Transhumance — avis du conseil (12/11/2026)

Cinq conseillers ont lu le dossier séparément ; cinq relecteurs ont jugé leurs réponses sans savoir qui avait écrit quoi. Synthèse du président.

## Là où le conseil est d'accord

- **L'ordre est le bon** : sonde, essai, petit dossier, puis le reste. Mais **une seule photo ne prouve rien** : l'essai doit porter sur un lot varié (une vidéo lourde, une photo animée, un visage posé à la main, une photo archivée, un fichier présent dans deux dossiers).
- **Tout arrêter pendant un lot** : carnet, Millésime, Treemich, les tâches de nuit d'Immich, le scan programmé de la bibliothèque externe, et tout envoi depuis le téléphone.
- **C'est l'appli qui retire les fichiers, pas Immich** : Immich ne supprime normalement pas un fichier de bibliothèque externe, et un scan le réimporterait.
- **Un visage recréé à la main est acceptable**, compté et dit en clair. Un visage perdu bloque.
- **La table ancien identifiant → nouvel identifiant est le seul livrable durable** : elle doit sortir de l'appli avant son retrait.
- **Trop habillé pour un outil qui sert une fois** : garder l'arbre, les cases, les noms d'albums et le bilan ; couper la pilule iPhone, l'écran Réglages, la signature graphique.

## Là où il se divise

- **Supprimer, déplacer, ou ne pas toucher.** Trois voix pour un **déplacement** des originaux dans un dossier « passés » sur le même volume, vidé à la main plus tard (instantané, pas plus de code qu'une suppression). Une voix pour que l'outil **ne touche jamais aux fichiers** (montage en lecture seule, effacement à la main dans l'explorateur du NAS après quelques semaines). Une voix contre toute corbeille. Les relecteurs objectent à la voie « ne pas toucher » : un effacement à la main, sans preuve fichier par fichier, est plus dangereux que le bouton. Et l'argument qui fait pencher : le dossier dit lui-même qu'une photo qui passe mal ne se voit pas le jour même, or la suppression aurait lieu le jour même.
- **Élargir ou non** (garder le chemin d'origine sur chaque photo, inventaire pour la frise, moteur réutilisable) : une voix pour, quatre relecteurs contre. Retenu seulement : le chemin d'origine dans la table de correspondance.

## Ce que la relecture a fait sortir

1. **Le plan protégeait la mauvaise chose.** L'empreinte garantit le fichier, qui est de toute façon sauvegardé. Ce qui se perd sans retour, c'est ce qu'Immich sait de l'ancienne photo : visages, albums, date ou lieu corrigés, visibilité. Il faut un **instantané complet de chaque ancienne photo**, gardé hors de l'appli, et une sauvegarde de la base d'Immich avant chaque lot.
2. **L'iPhone, qui est le but.** Quand l'appli Immich enverra la pellicule du téléphone, reconnaîtra-t-elle les photos déjà migrées ? Si les fichiers du téléphone ne sont pas, octet pour octet, ceux du dossier (conversion, retouche, photo animée), toute la pellicule se dédouble, sans visages ni albums. **À essayer sur dix photos avant tout le reste.**
3. **La sauvegarde « récente » recopiera les suppressions** à son passage suivant. Il faut une copie figée (ou un instantané du volume) avant la première suppression, et y inclure le stockage d'Immich.
4. **Le contrôle par personne** : même nombre de photos par personne avant et après, et aucune personne nouvelle (doubler chaque photo peut faire naître des personnes parasites).
5. **L'empreinte de l'ancienne photo** n'est probablement pas celle du contenu pour une photo externe : l'appli doit calculer elle-même l'empreinte du fichier, et la comparer à celle de la copie rangée.
6. **L'échelle** : des centaines de dossiers d'évènement, c'est autant de bilans. Bilan et retrait **par année**.
7. **Le retour arrière avant le clic** : rien ne disait comment défaire un dossier dont le bilan est mauvais.
8. **Synology Photos** : ses albums et ses partages disparaissent avec les fichiers ; son envoi depuis le téléphone doit être coupé avant de commencer.
9. **Figer Immich en 3.4.1** pendant toute la migration.
10. **Contrôles manquants** : paire photo + vidéo des photos animées, état archivé / masqué / verrouillé, note, fuseau de la date, taille et durée des vidéos, compte des fichiers du dossier (y compris ceux qu'Immich ignore) contre compte des nouvelles photos, chemin final après rangement.
11. **L'écran du clic** : une phrase en tête (« 312 fichiers, 312 retrouvés identiques, 0 laissé de côté »), chaque écart dit en clair ce qu'on perd, cinq photos tirées au hasard à ouvrir avant que le bouton s'active.

Deux pistes plus légères ont été soulevées par un relecteur. **Ne pas migrer** (geler la bibliothèque externe en archive, basculer seulement l'iPhone) : possible, mais laisse deux rangements pour toujours, ce que l'utilisateur ne veut pas. **Modifier la base d'Immich** pour « adopter » les photos en gardant leurs identifiants : écarté — chirurgie non prévue par Immich, sans accès à la machine, sur la base de toute la photothèque.

## Recommandation

Garder Transhumance, avec ces changements :

1. **Avant toute ligne d'appli : deux essais.** La sonde (lecture seule), et l'essai iPhone sur dix photos.
2. **Les originaux sont déplacés dans « passés »**, pas supprimés. l'utilisateur vide ce dossier lui-même, par année, quelques semaines plus tard. Le clic reste, il devient réversible.
3. **Instantané complet** de chaque ancienne photo et **table de correspondance**, écrits dans un fichier hors de l'appli.
4. **Contrôles par photo, par dossier et par personne**, avec la liste du point 10.
5. **Bilan et retrait par année** ; un bouton « Défaire ce dossier » tant que les originaux sont là.
6. **Tout arrêter pendant un lot** ; Immich figé en 3.4.1 ; envoi de Synology Photos coupé.
7. **Interface allégée** : arbre, cases, noms d'albums, bilan, Connexion. Pas d'iPhone, pas de Réglages.

## La première chose à faire

L'essai iPhone : dix photos déjà présentes dans la Pellicule, envoyées par l'appli Immich du téléphone, pour voir si Immich les reconnaît comme déjà là une fois migrées. Si non, c'est le plan entier qu'il faut revoir, pas l'outil.

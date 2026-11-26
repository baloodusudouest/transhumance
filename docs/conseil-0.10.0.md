# Transhumance 0.10.0 — avis du conseil (26/11/2026)

Dossier soumis : `transhumance-0.10.0-dossier.md`. Cinq conseillers (Contradicteur, Premiers principes, Expansionniste, Regard extérieur, Exécutant), relecture croisée anonyme par cinq relecteurs, synthèse du président.

Relecture : la réponse du **Contradicteur** est jugée la plus solide par 4 relecteurs sur 5 (le 5e choisit Premiers principes, très proche). Plus grand angle mort : **Expansionniste** (3 voix : enthousiasme, peu sur la suppression irréversible) et **Exécutant** (2 voix : rien sur la fidélité ni la copie cloud).

## Où le conseil s'accorde

- **La preuve prévue ne suffit pas pour supprimer.** Durée + vignette laissent passer un MP4 muet, tronqué ou à moitié noir. À ajouter, en **bloquant** : flux son présent si l'original en avait un (durée ±1 s), nombre d'images ±1 %, définition et rotation identiques, décodage complet de la copie rangée par Immich (`ffmpeg -v error -f null -` sans erreur), **comparaison d'images (SSIM) sur 3 à 5 instants** entre l'original et la copie.
- **HDR / 10 bits (vidéos d'iPhone)** : un passage en H.264 8 bits `yuv420p` délave les couleurs sans erreur visible. À détecter (`color_transfer` smpte2084 / arib-std-b67, `pix_fmt` 10 bits, Dolby Vision) et à ne pas aplatir.
- **Live Photos** : un `.mov` compagnon d'une photo (`livePhotoVideoId`) ne doit pas être réencodé à part ; le lien avec la photo casserait.
- **Quick Sync sur le DS1520+ n'est pas acquis** : `/dev/dri` absent par défaut sur DSM (pilote i915 à charger, souvent par une tâche au démarrage), pilote `iHD`, `LIBVA_DRIVER_NAME=iHD`. `h264_qsv` n'égale pas x264 CRF 18 : « quasi identique » à mesurer. **Premier geste : un essai réel** (`vainfo` + 10 s de `h264_qsv`) dans le conteneur sur le NAS. Si ça échoue, le NAS n'encode pas, et c'est un cas normal.
- **Vidéos inconnues** : la ligne dans `photos` est le bon choix (un seul chemin de suppression, mêmes garde-fous), mais avec un **champ `origine` explicite** plutôt qu'un préfixe `inconnu:` dans `ancien_id`. Décocher doit les remettre dans `inconnus`.
- **Plafond de taille** : si le MP4 dépasse 1,5 × l'original, réencoder plus léger (CRF 22-23) ; s'il reste plus gros, écart « grossi » et l'original n'est pas supprimé.

## Où le conseil diverge

- **Tout réencoder** (choix du propriétaire) contre **remuxer ce qui est déjà H.264/AAC** (4 conseillers sur 5). Pour : un seul format homogène, lecture partout. Contre : réencoder un H.264 ajoute une perte irréversible sans gain ; le remux (changement d'enveloppe en MP4, sans toucher l'image) est sans perte, beaucoup plus rapide, et garde une empreinte de l'image prouvable. **À trancher par le propriétaire.**
- **Sas avant suppression** : le Contradicteur veut une corbeille d'un mois pour les originaux vidéo ; d'autres jugent la copie cloud suffisante si elle est vérifiée.

## Angles morts relevés en relecture

- **Le code actuel suppose des fichiers identiques octet par octet** : `_controler`, `supprimer`, l'écart `empreinte` et le bilan. Pour une vidéo encodée, il faut un nouvel état et une preuve liée (empreinte du MP4 produit, rattachée à l'original), sinon le garde-fou bloque tout ou est contourné.
- **Changement de nom** (`.wma` → `.mp4`) : `rel`, `inconnus`, `_finis`, `correspondance.csv` doivent suivre ; **collision** avec un `.mp4` du même nom dans le dossier → suffixe.
- **`immich.envoyer`** pose `fileCreatedAt` depuis la date de modification du fichier et lit le fichier entier en mémoire pour le SHA-1 : il faut poser la date du MP4 (`os.utime`) avant l'envoi et calculer le SHA-1 en flux pour les grosses vidéos. Un « doublon » renvoyé par Immich ne prouve pas que c'est notre MP4.
- **`retirer(force=True)`** supprime l'ancienne entrée Immich sans corbeille : vérifier le report (visages, albums, tags) avant.
- **Bail de 2 h** trop court pour une longue vidéo encodée par le processeur : signal de vie par vidéo, et reprise propre si le PC s'endort ou coupe un transfert.
- **Copie cloud** : l'outil ne la vérifie pas. Tester une restauration de quelques vidéos avant le premier clic de suppression.
- `-map_metadata 0` ne garde pas tout (GPS, atomes Apple) : copier aussi les balises QuickTime utiles.
- Le flux `/calcul` (PC ↔ NAS) reste sur le réseau local ; jeton propre à Transhumance.
- Mesurer d'abord le gain : combien de vidéos, combien de Go.

## Idées pour plus tard (Expansionniste)

- La file `encodages` + porte `/calcul` + encodeur du PC = un **moteur de calcul commun** (Millésime, Scriptorium…) à extraire dans `socle`.
- Home Assistant réveille le PC (Wake-on-LAN, câble CPL branché pour ça) quand la file n'est pas vide.
- « Certificat de fidélité » (SSIM) affiché dans le bilan.

## Recommandation du président

Faire la 0.10.0, avec trois changements avant le go :
1. preuve renforcée (son, images, définition, décodage complet, SSIM), en bloquant ;
2. HDR / 10 bits et Live Photos traités à part (jamais aplatis, jamais séparés de leur photo) ;
3. une décision du propriétaire sur **réencoder tout** ou **remuxer ce qui est déjà H.264/AAC**, et sur un **sas** avant suppression.

## Premier geste

Essai Quick Sync réel sur le NAS (`vainfo` + 10 s de `h264_qsv` dans l'image), avant d'écrire la file NAS.

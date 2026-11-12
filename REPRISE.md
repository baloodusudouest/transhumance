# Reprise — Transhumance

À lire avant de toucher au dépôt. Dossier : `docs/dossier.md` ; avis du conseil : `docs/conseil.md`.

## Où on en est (12/11/2026)

- **0.1.0** : écrite et testée contre un **faux Immich** (`tests/faux_immich.py`), qui se comporte comme on
  suppose qu'Immich se comporte. **Jamais lancée sur le vrai.** Prochaine étape : l'essai sur un petit dossier.
- **0.1.5** : `Transhumance.reconnaissance()` lit `GET /system-config` (machineLearning.urls) et `GET /queues`, et interroge `/ping` de chaque adresse. **Forme de `/system-config` supposée, pas vue sur le vrai Immich** ; la clé doit avoir le droit de lire les réglages.
- Premier lot réel lancé le 12/11 (un dossier d'environ 2000 fichiers) : envoi accepté, contrôle en cours, aucun écart sur les premières photos.
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

## Limites connues

- La vignette d'une personne qui pointait sur une ancienne photo n'est pas repointée.
- Pas de contrôle « aucune personne nouvelle » après un lot.
- Interface pensée pour le PC.

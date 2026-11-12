# Transhumance

Fait passer les photos d'une **bibliothèque externe d'Immich** dans le **stockage d'Immich**, en gardant les
personnes, les albums, les tags et les dates, puis supprime les fichiers d'origine — sur un clic, après un bilan.
Outil d'une seule fois, à retirer de la stack quand la migration est finie.

Dossier de conception : `docs/dossier.md`. Avis du conseil : `docs/conseil.md`. Écrit pour Immich 3.4.

## Avant de commencer

1. Une copie figée de la photothèque existe hors du NAS.
2. Immich n'est pas mis à jour pendant la migration.
3. Une clé d'API Immich dédiée (droits : tout sur les photos, albums, tags, visages, personnes, bibliothèques en lecture,
   recherche, files en lecture, serveur en lecture).
4. Les applis qui écrivent dans Immich sont arrêtées pendant un lot.

## Parcours

1. **Relire Immich et le dossier** : l'arbre se remplit. Rien n'est écrit.
2. Cocher des dossiers, régler le nom d'album de chacun (vide : pas d'album).
3. **Faire passer les dossiers cochés** : les copies sont envoyées et contrôlées. Rien n'est supprimé.
4. **Bilan** : lire la phrase, régler les écarts, ouvrir l'échantillon dans Immich.
5. **Supprimer les originaux** : seuls les fichiers prouvés copiés partent. Un fichier qu'Immich ne connaît pas reste.

Tant que les originaux sont là, **Défaire** retire les copies et remet le dossier dans son état de départ.

## Variables

Voir `docker-compose.yml`. Sans `TRANSHUMANCE_PASSWORD`, `TRANSHUMANCE_IMMICH_CLE` et `TRANSHUMANCE_RACINE_IMMICH`,
le conteneur ne démarre pas. Premier lancement conseillé avec `TRANSHUMANCE_LECTURE_SEULE=oui`.

## Tests

```
pip install -r requirements-dev.txt && python -m pytest -q tests --ignore=tests/interface
cd frontend && npm ci && npx vite build && cd .. && pip install playwright && python -m pytest -q tests/interface
```

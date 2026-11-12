# Journal des versions

## 0.1.1 — 12 novembre 2026
- Icône de l'appli : une montagne et le chemin du troupeau.
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

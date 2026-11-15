<script>
  // « Connexion » : Immich, le dossier des photos et la reconnaissance. Journal, version, déconnexion : dans Réglages (0.5.0).
  import { onMount } from 'svelte'
  import { api } from '$lib/api.js'
  import { poids } from '$lib/format.js'
  import { Button } from '$lib/components/ui/button/index.js'
  import Reconnaissance from '$lib/Reconnaissance.svelte'

  let { ondeconnecte } = $props()
  let d = $state(null)
  let message = $state('')
  async function lire() { try { d = await api.get('/api/connexions') } catch (e) { if (e.statut === 401) ondeconnecte?.(); else message = e.message } }
  onMount(lire)
</script>

<header class="mb-5"><p class="etiquette">Transhumance</p><h1 class="titre">Connexion</h1></header>
{#if !d}
  <p class="text-sm text-muted-foreground">{message || 'Lecture…'}</p>
{:else}
  <div class="grid gap-3 md:grid-cols-2">
    <section class="rounded-2xl border bg-card p-5" aria-label="Immich">
      <h2 class="flex items-center justify-between text-lg font-semibold">Immich
        <span class="size-2.5 rounded-full {d.immich.ok ? 'bg-valide' : 'bg-muted-foreground/40'}" aria-hidden="true"></span></h2>
      {#if d.immich.ok}
        <p class="mt-1 text-sm">Version {d.immich.version} · {poids(d.immich.place_libre)} libres</p>
      {:else}<p class="mt-1 text-sm">{d.immich.erreur}</p>{/if}
      <p class="mt-2 text-sm text-muted-foreground">Transhumance y lit la bibliothèque externe, y envoie les copies, y reporte albums, tags et visages, puis en retire les anciennes photos. Ne mets pas Immich à jour pendant la migration.</p>
    </section>
    <section class="rounded-2xl border bg-card p-5" aria-label="Dossier des photos">
      <h2 class="flex items-center justify-between text-lg font-semibold">Dossier des photos
        <span class="size-2.5 rounded-full {d.dossier.lisible && d.dossier.inscriptible ? 'bg-valide' : 'bg-muted-foreground/40'}" aria-hidden="true"></span></h2>
      <p class="mt-1 text-sm">{d.dossier.lisible ? 'lisible' : 'illisible'} · {d.dossier.inscriptible ? 'écriture possible (nécessaire pour supprimer)' : 'écriture refusée : rien ne pourra être supprimé'}</p>
      <p class="mt-2 text-sm text-muted-foreground">Transhumance n'y écrit rien : elle y supprime seulement, sur ton clic, les fichiers prouvés copiés.
        {d.dossier.exclus.length ? `Jamais migrés : ${d.dossier.exclus.join(', ')}.` : ''}</p>
    </section>
    <Reconnaissance {ondeconnecte} />
  </div>
  <div class="mt-3"><Button variant="outline" onclick={lire}>Vérifier</Button></div>

{/if}

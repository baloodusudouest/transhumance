<script>
  // « Réglages » (0.5.0, format commun) : ce qui n'est pas un service — l'écriture, le journal des écritures —
  // puis, toujours en bas, la version et la déconnexion.
  import { onMount } from 'svelte'
  import { api } from '$lib/api.js'
  import { quand } from '$lib/format.js'
  import { Button } from '$lib/components/ui/button/index.js'

  let { session, deconnecter, ondeconnecte } = $props()
  let d = $state(null)
  let message = $state('')
  onMount(async () => {
    try { d = await api.get('/api/connexions') } catch (e) { if (e.statut === 401) ondeconnecte?.(); else message = e.message }
  })
</script>

<header class="mb-5"><p class="etiquette">Transhumance</p><h1 class="titre">Réglages</h1></header>

<section class="rounded-2xl border bg-card p-5" aria-label="Écriture">
  <h2 class="text-lg font-semibold">Écriture</h2>
  <p class="mt-1 text-sm text-muted-foreground">
    {session.lecture_seule
      ? "Lecture seule : Transhumance montre l'arbre et les bilans, n'envoie rien et ne supprime rien. À retirer dans la stack (TRANSHUMANCE_LECTURE_SEULE) pour migrer."
      : "Transhumance envoie et supprime sur ton clic. Pour seulement regarder : TRANSHUMANCE_LECTURE_SEULE=oui dans la stack."}
  </p>
  {#if d?.dossier.exclus.length}
    <p class="mt-2 text-sm text-muted-foreground">Jamais migrés : {d.dossier.exclus.join(', ')}.</p>
  {/if}
</section>

<section class="mt-4 rounded-2xl border bg-card p-5" aria-label="Journal">
  <h2 class="text-lg font-semibold">Journal</h2>
  {#if !d}
    <p class="mt-2 text-sm text-muted-foreground">{message || 'Lecture…'}</p>
  {:else}
    <ul class="mt-2 divide-y text-sm">
      {#each d.journal as l}
        <li class="flex flex-wrap justify-between gap-x-4 py-1.5"><span class="min-w-0">{l.quoi}</span><span class="text-muted-foreground">{quand(l.le)}</span></li>
      {:else}<li class="py-1.5 text-muted-foreground">Rien pour l'instant.</li>{/each}
    </ul>
  {/if}
</section>

<p class="mt-6 flex items-center justify-between gap-3 text-sm text-muted-foreground">
  <span>Transhumance {session.version || d?.version}</span>
  <Button variant="outline" onclick={deconnecter}>Se déconnecter</Button>
</p>

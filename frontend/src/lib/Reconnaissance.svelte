<script>
  // 0.1.5 : qui fait la reconnaissance d'Immich (visages, recherche, texte) — le PC ou le NAS ?
  // Immich essaie ses adresses dans l'ordre ; Transhumance pose la même question à chacune, toutes les dix secondes.
  import { onMount } from 'svelte'
  import { api } from '$lib/api.js'

  let { court = false, ondeconnecte } = $props()
  let r = $state(null)
  async function lire() { try { r = await api.get('/api/reconnaissance') } catch (e) { if (e.statut === 401) ondeconnecte?.() } }
  onMount(() => { lire(); const m = setInterval(lire, 10000); return () => clearInterval(m) })

  const verdict = $derived(!r ? 'Lecture…'
    : !r.lisible ? 'Réglages d\'Immich illisibles'
    : !r.active ? 'Reconnaissance désactivée dans Immich'
    : r.utilisee === null ? 'Aucun service de reconnaissance ne répond'
    : r.sur_pc ? 'Le PC fait la reconnaissance' : 'Le NAS fait la reconnaissance (le PC ne répond pas ou n\'est pas déclaré)')
  const reste = $derived((r?.files || []).reduce((s, f) => s + f.attente + f.en_cours, 0))
</script>

{#if court}
  <p class="mt-2 flex items-center gap-2 text-sm text-muted-foreground" id="reconnaissance-courte">
    <span class="size-2.5 flex-none rounded-full {r?.sur_pc ? 'bg-valide' : 'bg-muted-foreground/40'}" aria-hidden="true"></span>
    <span>{verdict}{r?.files?.length ? ` · ${reste} tâche(s) de reconnaissance en attente` : ''}</span></p>
{:else}
  <section class="rounded-2xl border bg-card p-5 md:col-span-2" aria-label="Reconnaissance d'Immich">
    <h2 class="flex items-center justify-between text-lg font-semibold">Reconnaissance d'Immich
      <span class="size-2.5 rounded-full {r?.sur_pc ? 'bg-valide' : 'bg-muted-foreground/40'}" aria-hidden="true"></span></h2>
    <p class="mt-1 text-sm font-medium" role="status">{verdict}</p>
    {#if r && !r.lisible}<p class="mt-1 text-sm">{r.raison}</p>{/if}
    {#if r?.adresses?.length}
      <ol class="mt-2 divide-y text-sm" aria-label="Adresses essayées par Immich">
        {#each r.adresses as a, i}
          <li class="flex flex-wrap items-baseline justify-between gap-x-4 py-1.5">
            <span class="min-w-0 break-all">{i + 1}. {a.nas ? 'NAS' : 'PC'} <span class="text-muted-foreground">· {a.adresse}</span></span>
            <span class={a.repond ? '' : 'text-muted-foreground'}>{a.repond ? (i === r.utilisee ? 'répond : c\'est lui qui travaille' : 'répond, en secours') : 'ne répond pas'}</span>
          </li>
        {/each}
      </ol>
    {/if}
    {#if r?.files?.length}
      <ul class="mt-3 divide-y text-sm" aria-label="Files de reconnaissance">
        {#each r.files as f}
          <li class="flex flex-wrap justify-between gap-x-4 py-1.5"><span>{f.nom}</span>
            <span class="text-muted-foreground">{f.en_cours ? `${f.en_cours} en cours · ` : ''}{f.attente} en attente</span></li>
        {/each}
      </ul>
    {/if}
    <p class="mt-2 text-sm text-muted-foreground">Immich essaie ces adresses dans l'ordre et prend la première qui répond. Transhumance leur pose la même question toutes les dix secondes : elle ne voit pas chaque calcul, mais si le PC répond en premier, c'est lui qu'Immich utilise. Elle ne change rien aux réglages d'Immich.</p>
  </section>
{/if}

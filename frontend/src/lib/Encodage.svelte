<script>
  // 0.10.0 : où en est la mise en MP4 des vidéos restantes — le PC (Docker Desktop), ou la puce vidéo du NAS ?
  // Relu toutes les dix secondes ; prévient l'écran Migrer quand la file bouge (pour relire l'arbre).
  import { onMount } from 'svelte'
  import { api } from '$lib/api.js'
  import { quand } from '$lib/format.js'

  let { ondeconnecte, onchange } = $props()
  let e = $state(null)
  let empreinte = ''
  async function lire() {
    try {
      e = await api.get('/api/encodage')
      const n = JSON.stringify([e.file, e.a_envoyer])
      if (empreinte && n !== empreinte) onchange?.()
      empreinte = n
    } catch (x) { if (x.statut === 401) ondeconnecte?.() }
  }
  onMount(() => { lire(); const m = setInterval(lire, 10000); return () => clearInterval(m) })

  const travail = $derived(e ? e.file.attente + e.file.pris + e.a_envoyer + e.file.erreurs : 0)
  const qui = $derived(!e ? '' : e.pc.actif ? `le PC (${e.pc.machine || 'sans nom'}) réencode`
    : e.nas.ok ? 'PC absent : la puce vidéo du NAS réencode à sa place'
    : 'PC absent et la puce vidéo du NAS indisponible : les réencodages attendent le PC')
</script>

{#if e && (travail || e.pc.vu_le)}
  <div class="mt-2 text-sm text-muted-foreground" id="encodage">
    <p class="flex items-center gap-2">
      <span class="size-2.5 flex-none rounded-full {e.file.pris ? 'bg-valide' : 'bg-muted-foreground/40'}" aria-hidden="true"></span>
      <span>Vidéos : {qui}{e.pc.actif || !e.pc.vu_le ? '' : ` (vu le ${quand(e.pc.vu_le)})`} · {e.file.attente} en attente
        {e.file.pris ? ` · ${e.file.pris} en cours` : ''}{e.a_envoyer ? ` · ${e.a_envoyer} prête(s) à partir` : ''}{e.file.erreurs ? ` · ${e.file.erreurs} impossible(s)` : ''}</span></p>
    {#each e.en_cours as c}
      <p class="ml-4 break-all">{c.voie === 'remux' ? 'Changement d\'enveloppe' : 'Réencodage'} de {c.fichier} par {c.par === 'pc' ? (c.machine || 'le PC') : 'le NAS'}</p>
    {/each}
    {#if !e.outils}<p class="ml-4">ffmpeg manque dans l'image : les vidéos ne peuvent pas être préparées.</p>{/if}
  </div>
{/if}

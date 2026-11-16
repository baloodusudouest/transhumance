<script>
  // « Réglages » (0.5.0, format commun) : ce qui n'est pas un service — l'écriture, les réglages d'usage (0.7.0),
  // la restauration d'une sauvegarde (0.7.0), le journal des écritures — puis, toujours en bas, la version et la
  // déconnexion.
  import { onMount } from 'svelte'
  import { api } from '$lib/api.js'
  import { quand } from '$lib/format.js'
  import { Button } from '$lib/components/ui/button/index.js'

  let { session, deconnecter, ondeconnecte } = $props()
  let d = $state(null)
  let message = $state('')
  const refus = (e, ou) => { if (e.statut === 401) ondeconnecte?.(); else ou(e.message) }

  // ---- réglages d'usage (0.7.0) : ils ne viennent plus de la stack
  let reglages = $state(null)
  let exclusTexte = $state('')
  let auto = $state(false)
  let msgReglages = $state('')
  let enregistre = $state(false)
  function prendre(r) { reglages = r; exclusTexte = r.exclus.join('\n'); auto = r.auto_demandes }
  const exclusSaisis = () => exclusTexte.split('\n').map((x) => x.trim()).filter(Boolean)
  const change = $derived(reglages && (exclusSaisis().join('\n') !== reglages.exclus.join('\n') || auto !== reglages.auto_demandes))
  async function enregistrer() {
    msgReglages = ''; enregistre = true
    try { prendre(await api.put('/api/reglages', { exclus: exclusSaisis(), auto_demandes: auto })); msgReglages = 'Réglages enregistrés.'; await lireJournal() }
    catch (e) { refus(e, (m) => (msgReglages = m)) }
    enregistre = false
  }

  // ---- restaurer une sauvegarde gardée par l'Anneau (0.7.0)
  let dates = $state(null)
  let le = $state('')
  let apercu = $state(null)
  let msgRestaurer = $state('')
  let restaure = $state(false)
  const NOMS = { exclus: 'Dossiers jamais migrés', auto_demandes: 'Passage automatique des demandes' }
  const montrer = (v) => Array.isArray(v) ? (v.length ? v.join(', ') : 'aucun') : typeof v === 'boolean' ? (v ? 'oui' : 'non') : String(v ?? '—')
  async function voirDates() {
    msgRestaurer = ''; apercu = null
    try { dates = (await api.get('/api/restaurer')).dates; le = dates[0] || ''; if (le) await voirApercu() }
    catch (e) { dates = null; refus(e, (m) => (msgRestaurer = m)) }
  }
  async function voirApercu() {
    msgRestaurer = ''; apercu = null
    if (!le) return
    try { apercu = await api.get('/api/restaurer?le=' + encodeURIComponent(le)) } catch (e) { refus(e, (m) => (msgRestaurer = m)) }
  }
  async function restaurer() {
    restaure = true; msgRestaurer = ''
    try {
      prendre(await api.post('/api/restaurer', { le }))
      msgRestaurer = `Réglages du ${le} restaurés.`; apercu = null; await lireJournal()
    } catch (e) { refus(e, (m) => (msgRestaurer = m)) }
    restaure = false
  }

  async function lireJournal() { try { d = await api.get('/api/connexions') } catch (e) { refus(e, (m) => (message = m)) } }
  onMount(async () => {
    try { prendre(await api.get('/api/reglages')) } catch (e) { refus(e, (m) => (msgReglages = m)) }
    await lireJournal()
  })
</script>

<header class="mb-5"><p class="etiquette">Transhumance</p><h1 class="titre">Réglages</h1></header>

<section class="rounded-2xl border bg-card p-5" aria-label="Écriture">
  <h2 class="text-lg font-semibold">Écriture</h2>
  <p class="mt-1 text-sm text-muted-foreground">
    <!-- 0.6.0 : la lecture seule vient de toute la maison (MAISON_LECTURE_SEULE) ou de cette appli (TRANSHUMANCE_LECTURE_SEULE) -->
    {#if !session.lecture_seule}
      Transhumance envoie et supprime sur ton clic. Pour seulement regarder : MAISON_LECTURE_SEULE=oui (toute la maison) ou TRANSHUMANCE_LECTURE_SEULE=oui (cette appli) dans la stack.
    {:else if session.lecture_seule_origine === 'maison'}
      Lecture seule pour toute la maison (MAISON_LECTURE_SEULE) : Transhumance montre l'arbre et les bilans, n'envoie rien et ne supprime rien. Pour migrer : retirer MAISON_LECTURE_SEULE, ou TRANSHUMANCE_LECTURE_SEULE=non pour cette appli seule.
    {:else}
      Lecture seule pour cette appli (TRANSHUMANCE_LECTURE_SEULE) : Transhumance montre l'arbre et les bilans, n'envoie rien et ne supprime rien. À retirer dans la stack pour migrer.
    {/if}
  </p>
</section>

<div class="mt-4 grid gap-4 md:grid-cols-2">
  <section class="min-w-0 rounded-2xl border bg-card p-5" aria-label="Réglages">
    <h2 class="text-lg font-semibold">Réglages</h2>
    <p class="mt-1 text-sm text-muted-foreground">Gardés par Transhumance et sauvegardés chaque nuit par l'Anneau. Ils ne touchent ni Immich ni tes photos.</p>
    {#if reglages}
      <label class="mt-3 block text-sm font-medium" for="exclus">Dossiers jamais migrés</label>
      <p class="text-xs text-muted-foreground">Un dossier de premier niveau par ligne. Il reste dans l'arbre, sans case à cocher.</p>
      <textarea id="exclus" rows="3" bind:value={exclusTexte} spellcheck="false"
                class="mt-1.5 w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm"></textarea>
      <label class="mt-3 flex cursor-pointer items-start gap-3 text-sm">
        <input type="checkbox" bind:checked={auto} class="mt-0.5 size-4 accent-[var(--app)]" />
        <span>Faire passer tout seuls les dossiers demandés par Millésime <span class="text-muted-foreground">(envoi et contrôle ; la suppression reste un clic)</span></span>
      </label>
      <div class="mt-4"><Button onclick={enregistrer} disabled={!change || enregistre}>Enregistrer</Button></div>
    {/if}
    {#if msgReglages}<p class="mt-2 text-sm" role="status">{msgReglages}</p>{/if}
  </section>

  <section class="min-w-0 rounded-2xl border bg-card p-5" aria-label="Restaurer">
    <h2 class="text-lg font-semibold">Restaurer</h2>
    <p class="mt-1 text-sm text-muted-foreground">Reprendre les réglages d'une sauvegarde gardée par l'Anneau. Seuls les réglages changent.</p>
    {#if dates === null}
      <div class="mt-3"><Button variant="outline" onclick={voirDates}>Voir les sauvegardes</Button></div>
    {:else}
      <label class="mt-3 block text-sm font-medium" for="date-sauvegarde">Sauvegarde du</label>
      <select id="date-sauvegarde" bind:value={le} onchange={voirApercu}
              class="mt-1.5 h-10 w-full min-w-0 rounded-lg border border-input bg-background px-3 text-sm">
        {#each dates as j}<option value={j}>{j}</option>{/each}
      </select>
      {#if apercu}
        {#if apercu.differences.length}
          <ul class="mt-3 divide-y text-sm" aria-label="Différences">
            {#each apercu.differences as x}
              <li class="py-1.5"><span class="font-medium">{NOMS[x.cle] || x.cle}</span><br />
                <span class="break-words text-muted-foreground">{montrer(x.actuel)} → {montrer(x.sauve)}</span></li>
            {/each}
          </ul>
          <div class="mt-3"><Button onclick={restaurer} disabled={restaure}>Restaurer ces réglages</Button></div>
        {:else}
          <p class="mt-3 text-sm text-muted-foreground">Rien à restaurer : les réglages sont déjà ceux de cette sauvegarde.</p>
        {/if}
      {/if}
    {/if}
    {#if msgRestaurer}<p class="mt-2 text-sm" role="status">{msgRestaurer}</p>{/if}
  </section>
</div>

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

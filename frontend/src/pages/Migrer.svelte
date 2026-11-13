<script>
  import Reconnaissance from '$lib/Reconnaissance.svelte'
  // « Migrer » : l'arborescence des dossiers. On coche, on règle le nom de l'album, on fait passer,
  // on lit le bilan, puis — seulement là — on supprime les originaux prouvés copiés.
  import { onMount, onDestroy } from 'svelte'
  import ChevronRight from '@lucide/svelte/icons/chevron-right'
  import { api } from '$lib/api.js'
  import { poids, quand } from '$lib/format.js'
  import { Button } from '$lib/components/ui/button/index.js'

  let { lectureSeule = false, ondeconnecte } = $props()
  let a = $state(null)            // l'arbre
  let ouverts = $state(new Set(['.']))
  let lot = $state(null)
  let bilan = $state(null)
  let message = $state('')
  let attente = $state('')
  let confirme = $state(false)    // « j'ai ouvert des photos de l'échantillon »
  let minuteur

  const refus = (e) => { if (e.statut === 401) ondeconnecte?.(); else message = e.message }
  const tache = $derived(a?.tache || { en_cours: false })
  const ETATS = { vue: 'à migrer', envoyee: 'envoyées', prete: 'copiées et contrôlées', ecart: 'avec un écart', supprimee: 'originaux supprimés' }

  async function lire() {
    try { a = await api.get('/api/arbre'); lot = await api.get('/api/lot') } catch (e) { refus(e) }
  }
  async function faire(nom, f, dit) {
    attente = nom; message = ''
    try { await f(); if (dit) message = dit } catch (e) { refus(e) }
    attente = ''
  }
  const inventaire = () => faire('inventaire', async () => { a = await api.post('/api/inventaire'); lot = await api.get('/api/lot') }, 'Immich et le dossier ont été relus.')
  const regler = (chemin, corps) => faire('', async () => { a = await api.post('/api/dossier', { chemin, ...corps }); lot = await api.get('/api/lot') })
  const migrer = () => faire('migrer', async () => { await api.post('/api/migrer'); await lire() })
  const voirBilan = (chemin) => faire('bilan', async () => { bilan = await api.get('/api/bilan?chemin=' + encodeURIComponent(chemin)); confirme = false })
  const accepter = (e, oui) => faire('', async () => { await api.post('/api/accepter', { ancien: e.ancien, oui }); await voirBilan(bilan.chemin) })
  // 0.1.8 : pendant que le clic travaille, l'écran relit l'avancement chaque seconde
  let avancee = $state(null)
  let ailleurs = $state(null)
  const supprimer = () => faire('supprimer', async () => {
    avancee = { fait: 0, total: bilan.a_supprimer, etape: 'fichiers' }
    const veille = setInterval(async () => { try { const s = await api.get('/api/suppression'); if (s.en_cours) avancee = s } catch { /* la barre attend */ } }, 1000)
    let r
    try { r = await api.post('/api/supprimer', { chemin: bilan.chemin, nombre: bilan.a_supprimer }) } finally { clearInterval(veille); avancee = null }
    bilan = r.bilan; confirme = false; await lire()
    message = `${r.supprimes} original(aux) supprimé(s)` + (r.gardes ? `, ${r.gardes} gardé(s) parce que la copie ou le fichier avait changé.` : '.')
  })
  const defaire = () => faire('defaire', async () => {
    const r = await api.post('/api/defaire', { chemin: bilan.chemin }); await lire(); await voirBilan(bilan.chemin)
    message = `${r.copies_retirees} copie(s) retirée(s) d'Immich : le dossier est revenu à son état de départ.`
  })
  function basculer(chemin) {
    const s = new Set(ouverts); s.has(chemin) ? s.delete(chemin) : s.add(chemin); ouverts = s
  }
  const resume = (n) => Object.entries(n.etats).filter(([, v]) => v).map(([k, v]) => `${v} ${ETATS[k] || k}`).join(' · ')
  // 0.1.7 : un dossier fini (tous ses originaux supprimés) quitte l'arbre ; un lien le remontre
  let voirFinis = $state(false)
  const nbFinis = $derived(a ? Object.values(a.noeuds).filter((n) => n.chemin !== '.' && range(n) && !range(a.noeuds[parent(n.chemin)] || {photos: 0, videos: 0, etats: {}})).length : 0)
  const range = (n) => fini(n) && !n.inconnus      // un dossier où il reste des fichiers inconnus d'Immich reste visible
  const parent = (c) => (c.includes('/') ? c.slice(0, c.lastIndexOf('/')) : '.')
  const fini = (n) => (n.photos + n.videos) > 0 && (n.etats.supprimee || 0) === n.photos + n.videos
  const avance = (n) => (n.photos + n.videos) ? ((n.etats.prete || 0) + (n.etats.supprimee || 0)) / (n.photos + n.videos) : 0

  onMount(async () => { await lire(); minuteur = setInterval(async () => {
    if (a?.tache?.en_cours) lire()
    // une suppression lancée depuis une page fermée ou coupée continue : on la montre quand même
    if (attente !== 'supprimer') { try { const s = await api.get('/api/suppression'); ailleurs = s.en_cours ? s : null } catch { ailleurs = null } }
  }, 2000) })
  onDestroy(() => clearInterval(minuteur))
</script>

<header class="mb-5"><p class="etiquette">Transhumance</p><h1 class="titre">Migrer</h1></header>

{#if !a}
  <p class="text-sm text-muted-foreground">{message || 'Lecture…'}</p>
{:else}
  <section class="mb-4 rounded-2xl border bg-card p-4" aria-label="Lot">
    <div class="flex flex-wrap items-center gap-2">
      <Button variant="outline" onclick={inventaire} disabled={!!attente || tache.en_cours}>{attente === 'inventaire' ? 'Lecture d\'Immich…' : 'Relire Immich et le dossier'}</Button>
      <Button onclick={migrer} disabled={!!attente || tache.en_cours || lectureSeule || !lot?.dossiers.length || !lot?.possible}>
        Faire passer les dossiers cochés ({lot?.dossiers.length || 0})</Button>
      {#if lot?.dossiers.length}
        <span class="text-sm text-muted-foreground">{poids(lot.besoin)} à copier · {poids(lot.libre)} libres{lot.possible ? '' : ' — pas assez de place : coche moins de dossiers'}</span>
      {/if}
    </div>
    <p class="mt-2 text-sm text-muted-foreground">
      {a.inventaire ? `Dernière lecture le ${quand(a.inventaire.le)} : ${a.inventaire.photos} photos et vidéos dans la bibliothèque externe, ${a.inventaire.inconnus ?? '(parcours du dossier non terminé)'} fichier(s) qu'Immich ne connaît pas.` : 'Commence par relire Immich et le dossier.'}
      Faire passer ne supprime rien.</p>
    {#if tache.en_cours}
      <p class="mt-2 text-sm" role="status" id="tache">{tache.message} {tache.total ? `(${tache.fait} / ${tache.total})` : ''}</p>
    {:else if tache.erreur}
      <p class="mt-2 text-sm font-medium" role="alert">Lot interrompu : {tache.erreur}</p>
    {:else if tache.message}<p class="mt-2 text-sm" role="status" id="tache">{tache.message}</p>{/if}
    {#if ailleurs}<p class="mt-2 text-sm" role="status" id="suppression-en-cours">Suppression en cours dans « {ailleurs.dossier} » : {ailleurs.fait} sur {ailleurs.total}.</p>{/if}
    <Reconnaissance court {ondeconnecte} />
    <!-- 0.4.0 : les dossiers que Millésime a fini de dater passent tout seuls (envoi et contrôle seulement) -->
    <label class="auto mt-3">
      <input type="checkbox" checked={a.auto_demandes} disabled={!!attente || lectureSeule}
             onchange={(e) => faire('auto', async () => { a = await api.post('/api/auto-demandes', { oui: e.currentTarget.checked }) },
                                    e.currentTarget.checked ? 'Les dossiers demandés par Millésime passeront tout seuls.' : 'Passage automatique coupé.')} />
      <span><strong>Faire passer tout seuls les dossiers demandés par Millésime</strong>
        <span class="block text-sm text-muted-foreground">Dès qu'un dossier est entièrement daté dans Millésime, il est envoyé et contrôlé ici, un à la fois, quand aucun lot ne tourne. Les originaux ne sont jamais supprimés sans ton clic, après le bilan.</span></span>
    </label>
  </section>
  {#if message}<p class="mb-3 text-sm" role="status" id="message">{message}</p>{/if}

  {#if bilan}
    <section class="mb-4 rounded-2xl border border-primary/60 bg-card p-5" aria-label="Bilan">
      <div class="flex flex-wrap items-start justify-between gap-2">
        <h2 class="text-lg font-semibold">Bilan de « {bilan.chemin === '.' ? 'tout' : bilan.chemin} »</h2>
        <Button variant="outline" onclick={() => (bilan = null)}>Fermer</Button>
      </div>
      <p class="mt-2 text-[1.02rem] leading-snug" id="phrase-bilan">{bilan.phrase}</p>
      <p class="mt-2 text-sm text-muted-foreground">Personnes nommées : {bilan.visages.seul} reconnues toutes seules par Immich, {bilan.visages.reaffecte} rattachées par Transhumance,
        {bilan.visages.recree} recréées à la main (Immich ne les redétectait pas), {bilan.visages.perdu} perdues.
        {bilan.deja_la ? ` ${bilan.deja_la} photo(s) étaient déjà dans le stockage d'Immich.` : ''}</p>

      {#if bilan.ecarts.length}
        <h3 class="etiquette mt-4">Écarts ({bilan.ecarts.length})</h3>
        <ul class="mt-1 divide-y text-sm" aria-label="Écarts">
          {#each bilan.ecarts as e (e.ancien + e.sorte)}
            <li class="flex flex-wrap items-center justify-between gap-2 py-2">
              <span class="min-w-0"><span class="block break-all font-medium">{e.fichier}</span>
                <span class="block">{e.phrase}{e.personnes.length ? ` Concernées : ${e.personnes.join(', ')}.` : ''}</span>
                {#if e.bloquant}<span class="block text-muted-foreground">Ne s'accepte pas : l'original reste en place quoi qu'il arrive.</span>{/if}</span>
              {#if !e.bloquant}
                <Button variant="outline" onclick={() => accepter(e, !e.accepte)}>{e.accepte ? 'Accepté — revenir dessus' : 'J\'accepte cette perte'}</Button>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}

      {#if bilan.fichiers_inconnus.length}
        <details class="mt-4 text-sm">
          <summary class="etiquette cursor-pointer">Fichiers qu'Immich ne connaît pas ({bilan.inconnus}) — ils restent dans le dossier</summary>
          <ul class="mt-1 max-h-60 overflow-auto">{#each bilan.fichiers_inconnus as f}<li class="break-all">{f}</li>{/each}</ul>
          {#if bilan.inconnus > bilan.fichiers_inconnus.length}<p class="text-muted-foreground">Les {bilan.fichiers_inconnus.length} premiers sont montrés.</p>{/if}
        </details>
      {/if}

      {#if bilan.echantillon.length}
        <h3 class="etiquette mt-4">À ouvrir dans Immich avant de supprimer</h3>
        <ul class="mt-1 text-sm">
          {#each bilan.echantillon as p}
            <li class="break-all">{#if a.immich_adresse}<a class="underline" href={`${a.immich_adresse}/photos/${p.nouveau}`} target="_blank" rel="noopener">{p.fichier}</a>{:else}{p.fichier}{/if}</li>
          {/each}
        </ul>
        <p class="mt-1 text-sm text-muted-foreground">Vérifie sur chacune : la date, les personnes, l'album.</p>
      {/if}

      <div class="mt-4 rounded-xl bg-secondary p-4">
        {#if bilan.termine}
          <p class="text-sm" id="termine">Il n'y a plus rien à faire ici. Le dossier vide reste sur le NAS : tu peux l'effacer à la main quand tu veux.</p>
        {:else if bilan.supprimable}
          <p class="text-sm"><strong class="font-semibold">Supprimer définitivement {bilan.a_supprimer} fichier(s) d'origine</strong> de ce dossier, et retirer les anciennes photos d'Immich.
            Les copies restent dans Immich. {bilan.inconnus ? `Les ${bilan.inconnus} fichier(s) qu'Immich ne connaît pas restent dans le dossier.` : ''} Il n'y a pas de corbeille : le seul retour est ta sauvegarde.</p>
          <label class="mt-2 flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" class="size-5 accent-[var(--app)]" bind:checked={confirme} />
            J'ai ouvert des photos de ce lot dans Immich, elles sont bonnes.</label>
          <div class="mt-2"><Button variant="destructive" onclick={supprimer} disabled={!confirme || !!attente || lectureSeule}>
            {attente === 'supprimer' ? 'Suppression…' : `Supprimer les ${bilan.a_supprimer} originaux`}</Button></div>
          {#if avancee}
            <div class="mt-3" id="avancee">
              <div class="barre" role="progressbar" aria-label="Suppression des originaux" aria-valuemin="0" aria-valuemax={avancee.total} aria-valuenow={avancee.fait}>
                <div class="rempli" style:width="{avancee.total ? Math.round(100 * avancee.fait / avancee.total) : 0}%"></div></div>
              <p class="mt-1 text-sm text-muted-foreground" role="status">{avancee.etape === 'immich'
                ? `Fichiers traités (${avancee.total}). Retrait des anciennes photos d'Immich…`
                : `${avancee.fait} sur ${avancee.total} : chaque copie est relue, puis l'original est supprimé. Ne ferme pas cette page.`}</p>
            </div>
          {/if}
        {:else}
          <p class="text-sm">Pas encore supprimable : {bilan.a_supprimer ? (tache.en_cours ? 'le contrôle est en cours, reviens quand le lot est fini.' : bilan.etats.envoyee ? 'des photos envoyées attendent leur contrôle : relance « Faire passer ».' : 'un écart reste à régler, ou des photos ne sont pas passées.') : 'aucune photo de ce dossier n\'est copiée et contrôlée.'}</p>
        {/if}
        {#if (bilan.etats.prete || 0) + (bilan.etats.ecart || 0) + (bilan.etats.envoyee || 0)}
          <div class="mt-3"><Button variant="outline" class="h-auto min-h-10 max-w-full whitespace-normal py-2 text-left" onclick={defaire} disabled={!!attente || tache.en_cours || lectureSeule}>Défaire ce dossier (retirer les copies d'Immich)</Button></div>
        {/if}
      </div>
    </section>
  {/if}

  <section class="rounded-2xl border bg-card p-2 md:p-4" aria-label="Dossiers">
    {#if nbFinis}
      <p class="mb-2 flex flex-wrap items-center gap-2 text-sm text-muted-foreground" id="finis">
        <span>{nbFinis} dossier(s) terminé(s){voirFinis ? '' : ', masqué(s)'} : photos dans Immich, originaux supprimés.</span>
        <button type="button" class="underline underline-offset-2 hover:text-foreground" onclick={() => (voirFinis = !voirFinis)}>{voirFinis ? 'Masquer' : 'Afficher'}</button></p>
    {/if}
    {#if a.noeuds['.']}{@render branche(a.noeuds['.'], 0)}
    {:else}<p class="p-3 text-sm text-muted-foreground">Aucun dossier : relis Immich et le dossier.</p>{/if}
  </section>
{/if}

{#snippet branche(n, niveau)}
  {#if voirFinis || !range(n) || n.chemin === '.'}
  <div class="noeud" class:passe={fini(n)} style:--avance={avance(n)}>
    <div class="ligne" style:padding-left="{niveau * 1.1}rem">
      {#if n.enfants.length}
        <button type="button" class="pli" aria-expanded={ouverts.has(n.chemin)} aria-label={(ouverts.has(n.chemin) ? 'Replier ' : 'Déplier ') + n.nom} onclick={() => basculer(n.chemin)}>
          <ChevronRight class="size-4 transition-transform {ouverts.has(n.chemin) ? 'rotate-90' : ''}" aria-hidden="true" /></button>
      {:else}<span class="pli" aria-hidden="true"></span>{/if}
      <!-- Case pleine : tout ce dossier est coché. Case barrée d'un trait : une partie seulement, dans ses sous-dossiers.
           Décocher une case qu'on avait remplie depuis un choix partiel rend ce choix (0.1.3). -->
      <input type="checkbox" class="size-5 flex-none accent-[var(--app)]" checked={n.selection === 'tout'} indeterminate={n.selection === 'partiel'}
             disabled={n.exclu || tache.en_cours || !n.a_cocher}
             aria-label={'Cocher ' + n.nom} aria-checked={n.selection === 'partiel' ? 'mixed' : n.selection === 'tout'}
             title={n.selection === 'partiel' ? `${n.coches} sous-dossier(s) cochés sur ${n.a_cocher}` : n.souvenir ? `Décocher revient aux ${n.souvenir} sous-dossier(s) cochés avant` : ''}
             onchange={(e) => regler(n.chemin, { coche: n.selection === 'partiel' ? true : e.currentTarget.checked })} />
      <span class="min-w-0 flex-1">
        <span class="block truncate font-medium">{n.nom}{#if n.exclu}&nbsp;<span class="font-normal text-muted-foreground">· jamais migré</span>{/if}{#if n.demande}&nbsp;<span class="demande" title={'Demandé le ' + quand(n.demande.le)}>demandé par {n.demande.de}</span>{/if}</span>
        <span class="block truncate text-[0.82rem] text-muted-foreground">{n.photos} photo(s){n.videos ? `, ${n.videos} vidéo(s)` : ''} · {poids(n.poids)}{resume(n) ? ' · ' + resume(n) : ''}{n.inconnus ? ` · ${n.inconnus} inconnu(s) d'Immich` : ''}{n.selection === 'partiel' ? ` · ${n.coches} sous-dossier(s) cochés sur ${n.a_cocher}` : ''}{#if n.selection === 'partiel' && !tache.en_cours}&nbsp;· <button type="button" class="underline underline-offset-2 hover:text-foreground" aria-label={'Tout décocher dans ' + n.nom} onclick={() => regler(n.chemin, { coche: false, vider: true })}>tout décocher</button>{/if}</span>
      </span>
      {#if n.ici && !n.exclu}
        <input class="album" aria-label={'Album pour ' + n.nom} placeholder="pas d'album" value={n.album || ''} disabled={tache.en_cours}
               onchange={(e) => regler(n.chemin, { album: e.currentTarget.value })} />
      {/if}
      <Button variant="outline" onclick={() => voirBilan(n.chemin)} disabled={!!attente}>Bilan</Button>
    </div>
    {#if n.enfants.length && ouverts.has(n.chemin)}
      {#each n.enfants as c (c)}{@render branche(a.noeuds[c], niveau + 1)}{/each}
    {/if}
  </div>
  {/if}
{/snippet}

<style>
  /* 0.3.0 : un dossier qu'une autre appli demande de faire passer */
  .auto { display: flex; gap: 0.75rem; align-items: flex-start; cursor: pointer; }
  .auto input { width: 1.25rem; height: 1.25rem; margin-top: 0.15rem; accent-color: var(--app); flex: none; }
  .demande { font-weight: 500; font-size: 0.78rem; padding: 0.05rem 0.5rem; border-radius: 999px; border: 1px solid var(--app); color: var(--app); }
  .barre { height: 0.6rem; border-radius: 9999px; background: var(--border); overflow: hidden; }
  .rempli { height: 100%; border-radius: 9999px; background: var(--destructive, #c8553d); transition: width 0.4s ease; }
  /* Signature : un trait vert descend le long de ce qui est passé */
  .noeud { border-left: 3px solid color-mix(in srgb, var(--app) calc(var(--avance) * 100%), transparent); }
  .ligne { display: flex; align-items: center; gap: 0.6rem; padding: 0.4rem 0.5rem; border-radius: 0.6rem; }
  .ligne:hover { background: var(--secondary); }
  .pli { display: grid; place-items: center; width: 1.75rem; height: 1.75rem; flex: none; border-radius: 0.4rem; }
  .album { flex: 0 1 17rem; min-width: 8rem; height: 2.25rem; padding: 0 0.6rem; border-radius: 0.5rem; border: 1px solid var(--input);
    background: var(--background); font-size: 0.85rem; }
  .album:focus { outline: 2px solid var(--ring); outline-offset: 1px; }
  @media (max-width: 899px) { .ligne { flex-wrap: wrap; } .album { flex-basis: 100%; } }
</style>

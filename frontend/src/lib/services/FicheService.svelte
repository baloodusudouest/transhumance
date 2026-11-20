<script>
  // Fiche d'un service extérieur (contrat 3 des applis maison, socle 0.10.0).
  // Fichier COMMUN : écrit dans baloodusudouest/socle (frontend/src/lib/services/), copié TEL QUEL dans chaque appli
  // par tools/diffuser_maison.py ; la dernière ligne porte une empreinte que les tests de l'appli recalculent.
  // Ne le modifier que dans le socle. Aucune dépendance : classes Tailwind sur les jetons communs
  // (card, border, muted-foreground, primary, destructive, input).
  //
  // service : une entrée de GET /api/maison/services
  //   { id, nom, etat (repond | ne_repond_pas | relie | pas_relie), lit, ecrit, reglage, detail,
  //     verifie_le, derniere_ecriture, gestes: [{ id, nom }], guide (0.11.0, facultatif) }
  // guide : { reglages: [{ nom, valeur }], allumer: [phrase], pannes: [{ signe, faire: [phrase], commandes: [ligne] }],
  //           une_fois: [{ texte, commande }], terminal, note } — pour un service qu'on allume et répare soi-même
  // onverifier(service) : lance « Vérifier » (contour, ne teste que ce service, n'écrit rien)
  // ongeste(service, geste) : le geste qui écrit (Synchroniser, Livrer…), seul bouton plein de la fiche
  // enCours : « verifier », l'id du geste en cours, ou ''
  // simule : fiche du Bac à sable (bandeau « Simulé »)
  // message : phrase visible sous la fiche (erreur, résultat d'un geste) ; annonce : lue seulement par le lecteur d'écran
  let {
    service,
    onverifier = null,
    ongeste = null,
    enCours = '',
    lectureSeule = false,
    simule = false,
    message = '',
    annonce = '',
    titreNiveau = 2,
  } = $props()

  const MOTS = { repond: 'Répond', ne_repond_pas: 'Ne répond pas', relie: 'Relié', pas_relie: 'Pas relié' }
  const regle = $derived(service.etat !== 'pas_relie')
  const geste = $derived(service.gestes?.[0] ?? null)
  // 0.11.1 : « reglage » qui parle de Réglages (un réglage de l'appli, pas une variable) : « Pour le relier » seul
  const titreRelier = $derived((service.reglage || '').includes('Réglages') ? 'Pour le relier' : 'Pour le relier, dans la stack')

  const guide = $derived(service.guide ?? null)
  let copie = $state('')
  async function copier(texte) {
    try { await navigator.clipboard.writeText(texte) } catch {
      const zone = document.createElement('textarea')
      zone.value = texte
      document.body.appendChild(zone)
      zone.select()
      try { document.execCommand('copy') } catch { /* rien */ }
      zone.remove()
    }
    copie = texte
    setTimeout(() => { if (copie === texte) copie = '' }, 1500)
  }

  // « il y a 3 h » : l'âge d'une date ISO, en mots
  function age(iso) {
    if (!iso) return ''
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
    if (!Number.isFinite(s)) return ''
    if (s < 60) return "à l'instant"
    if (s < 3600) return `il y a ${Math.round(s / 60)} min`
    if (s < 86400) return `il y a ${Math.round(s / 3600)} h`
    const j = Math.round(s / 86400)
    return `il y a ${j} jour${j > 1 ? 's' : ''}`
  }
</script>

<article class="rounded-2xl border bg-card p-5 text-card-foreground" aria-labelledby={'service-' + service.id}>
  <div class="flex items-center gap-2.5">
    <span
      aria-hidden="true"
      class="size-2.5 shrink-0 rounded-full {service.etat === 'repond'
        ? 'bg-primary'
        : service.etat === 'ne_repond_pas'
          ? 'bg-destructive'
          : service.etat === 'relie'
            ? 'bg-muted-foreground'
            : 'border-2 border-muted-foreground'}"
    ></span>
    <svelte:element this={'h' + titreNiveau} id={'service-' + service.id} class="text-lg font-semibold leading-tight">
      {service.nom}
    </svelte:element>
    {#if simule}<span class="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">Simulé</span>{/if}
    <span class="ml-auto text-sm {service.etat === 'ne_repond_pas' ? 'text-destructive' : 'text-muted-foreground'}">
      {MOTS[service.etat] ?? service.etat}
    </span>
  </div>

  <dl class="mt-4 grid gap-3 text-[0.95rem] leading-snug">
    <div>
      <dt class="text-sm text-muted-foreground">Ce qui est lu</dt>
      <dd class="mt-0.5">{service.lit}</dd>
    </div>
    <div>
      <dt class="text-sm text-muted-foreground">Ce qui est écrit</dt>
      <dd class="mt-0.5">{service.ecrit}</dd>
    </div>
    {#if !regle && service.reglage}
      <div>
        <dt class="text-sm text-muted-foreground">{titreRelier}</dt>
        <dd class="mt-0.5 font-mono text-sm">{service.reglage}</dd>
      </div>
    {/if}
  </dl>

  {#if regle && (service.detail || service.verifie_le || service.derniere_ecriture)}
    <p class="mt-3 text-sm text-muted-foreground">
      {#if service.detail}<span class={service.etat === 'ne_repond_pas' ? 'text-destructive' : 'text-foreground'}>{service.detail}</span>{/if}
      {#if service.verifie_le}<span>{service.detail ? ' · ' : ''}Vérifié {age(service.verifie_le)}</span>{/if}
      {#if service.derniere_ecriture}<span>{service.detail || service.verifie_le ? ' · ' : ''}Dernière écriture {age(service.derniere_ecriture)}</span>{/if}
    </p>
  {/if}

  <p class="sr-only" aria-live="polite">{annonce || message || (enCours === 'verifier' ? 'Vérification en cours.' : '')}</p>
  {#if message}<p class="mt-3 text-sm" role="status">{message}</p>{/if}

  {#if regle && (onverifier || (geste && ongeste))}
    <div class="mt-4 flex flex-wrap items-center gap-2">
      {#if onverifier}
        <button
          type="button"
          class="inline-flex min-h-11 items-center rounded-xl border border-input px-4 text-[0.95rem] font-medium transition-colors hover:bg-foreground/5 disabled:opacity-60"
          aria-busy={enCours === 'verifier'}
          disabled={!!enCours}
          onclick={() => onverifier(service)}
        >{enCours === 'verifier' ? 'Vérification…' : 'Vérifier'}</button>
      {/if}
      {#if geste && ongeste}
        <button
          type="button"
          class="inline-flex min-h-11 items-center rounded-xl bg-primary px-4 text-[0.95rem] font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
          aria-busy={enCours === geste.id}
          disabled={!!enCours || lectureSeule}
          title={lectureSeule ? 'Mode lecture seule : rien n\'est écrit.' : undefined}
          onclick={() => ongeste(service, geste)}
        >{enCours === geste.id ? geste.nom + '…' : geste.nom}</button>
        {#if lectureSeule}<span class="text-sm text-muted-foreground">Lecture seule : rien n'est écrit.</span>{/if}
      {/if}
    </div>
  {/if}
  {#if guide}
    {#snippet commande(texte)}
      <span class="mt-1.5 flex items-start gap-2">
        <code class="min-w-0 flex-1 whitespace-pre-wrap break-all rounded-lg bg-background/70 px-2.5 py-1.5 font-mono text-xs">{texte}</code>
        <button type="button" class="min-h-8 shrink-0 rounded-lg border px-2.5 text-xs text-muted-foreground hover:text-foreground"
                aria-label="Copier la commande" onclick={() => copier(texte)}>{copie === texte ? 'Copié' : 'Copier'}</button>
      </span>
    {/snippet}
    {#if guide.reglages?.length}
      <dl class="mt-5 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
        {#each guide.reglages as r}<dt class="text-muted-foreground">{r.nom}</dt><dd class="break-words">{r.valeur}</dd>{/each}
      </dl>
    {/if}
    {#if guide.allumer?.length}
      <svelte:element this={'h' + (titreNiveau + 1)} class="mt-5 font-semibold">Allumer normalement</svelte:element>
      <ol class="mt-2 grid list-decimal gap-1.5 pl-5 text-sm">{#each guide.allumer as etape}<li>{etape}</li>{/each}</ol>
    {/if}
    {#if guide.pannes?.length}
      <svelte:element this={'h' + (titreNiveau + 1)} class="mt-5 font-semibold">En cas de problème</svelte:element>
      {#if guide.terminal}<p class="text-xs text-muted-foreground">{guide.terminal}</p>{/if}
      <div class="mt-2 grid gap-2">
        {#each guide.pannes as p}
          <details class="rounded-xl border px-3 py-2 open:bg-background/40">
            <summary class="min-h-8 cursor-pointer py-1 text-sm font-medium">{p.signe}</summary>
            {#if p.faire?.length}<ul class="mt-2 grid list-disc gap-1 pl-5 text-sm">{#each p.faire as x}<li>{x}</li>{/each}</ul>{/if}
            {#each p.commandes ?? [] as c}{@render commande(c)}{/each}
          </details>
        {/each}
      </div>
    {/if}
    {#if guide.une_fois?.length}
      <details class="mt-4 rounded-xl border px-3 py-2">
        <summary class="min-h-8 cursor-pointer py-1 text-sm font-medium">Installation (une seule fois)</summary>
        <ol class="mt-2 grid list-decimal gap-2 pl-5 text-sm">
          {#each guide.une_fois as u}<li>{u.texte}{#if u.commande}{@render commande(u.commande)}{/if}</li>{/each}
        </ol>
      </details>
    {/if}
    {#if guide.note}<p class="mt-3 text-xs text-muted-foreground">{guide.note}</p>{/if}
  {/if}
</article>
<!-- empreinte: 03a0545118b2ca5f -->

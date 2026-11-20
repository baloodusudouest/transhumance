<script>
  // Écran « Connexion » commun (contrat 3 des applis maison, socle 0.10.0) : les services extérieurs de l'appli.
  // Fichier COMMUN : écrit dans baloodusudouest/socle (frontend/src/lib/services/), copié TEL QUEL dans chaque appli
  // par tools/diffuser_maison.py ; la dernière ligne porte une empreinte que les tests de l'appli recalculent.
  // Ne le modifier que dans le socle. Aucune dépendance (fetch direct, même origine).
  //
  // De 1 à 3 services : les fiches sont dépliées. À partir de 4 : des tuiles à voyant ; la fiche s'ouvre dessous
  // au toucher (une seule à la fois), défile jusqu'à l'écran et prend le focus ; Échap la referme.
  //
  // ongeste(service, geste) : le geste qui écrit, porté par l'appli (ex. POST /api/synchroniser). Peut rendre une
  //   phrase à afficher sous la fiche ; une exception affiche son message. La liste est relue ensuite.
  // ondeconnecte() : appelé sur une réponse 401 (retour à l'écran du mot de passe).
  import { onMount, tick } from 'svelte'
  import FicheService from './FicheService.svelte'

  let {
    titre = 'Connexion',
    etiquette = '',
    ongeste = null,
    lectureSeule = false,
    ondeconnecte = null,
    adresse = '/api/maison/services',
    seuil = 3,
  } = $props()

  let reponse = $state(null)          // { contrat, appli, simule, services }
  let erreur = $state('')
  let ouvert = $state(null)           // id du service ouvert (mode tuiles)
  let enCours = $state({})            // { id: 'verifier' | id du geste }
  let messages = $state({})           // { id: phrase visible (erreur, résultat d'un geste) }
  let annonces = $state({})           // { id: phrase lue par le lecteur d'écran (résultat de Vérifier) }
  let ficheOuverte = $state(null)     // élément de la fiche ouverte (focus, défilement)

  const services = $derived(reponse?.services ?? [])
  const enTuiles = $derived(services.length > seuil)
  const choisi = $derived(services.find((s) => s.id === ouvert) ?? null)
  const MOTS = { repond: 'Répond', ne_repond_pas: 'Ne répond pas', relie: 'Relié', pas_relie: 'Pas relié' }

  async function appel(methode, chemin) {
    const r = await fetch(chemin, { method: methode, credentials: 'same-origin', headers: { Accept: 'application/json' } })
    let corps = null
    try { corps = await r.json() } catch { /* réponse vide */ }
    if (r.status === 401) { ondeconnecte?.(); throw new Error('Connexion nécessaire.') }
    if (!r.ok) throw new Error(corps?.detail || `Le serveur a répondu ${r.status}.`)
    return corps
  }

  async function lire() {
    try {
      reponse = await appel('GET', adresse)
      erreur = ''
    } catch (e) {
      erreur = e.message
    }
  }

  function remplacer(fiche) {
    if (!reponse || !fiche?.id) return
    reponse = { ...reponse, services: reponse.services.map((s) => (s.id === fiche.id ? fiche : s)) }
  }

  async function verifier(s) {
    enCours = { ...enCours, [s.id]: 'verifier' }
    messages = { ...messages, [s.id]: '' }
    annonces = { ...annonces, [s.id]: '' }
    try {
      const fiche = await appel('POST', `${adresse}/${encodeURIComponent(s.id)}/verifier`)
      remplacer(fiche)
      annonces = { ...annonces, [s.id]: `${fiche.nom} : ${(MOTS[fiche.etat] ?? fiche.etat).toLowerCase()}.` }
    } catch (e) {
      messages = { ...messages, [s.id]: e.message }
    }
    enCours = { ...enCours, [s.id]: '' }
  }

  async function geste(s, g) {
    if (!ongeste) return
    enCours = { ...enCours, [s.id]: g.id }
    messages = { ...messages, [s.id]: '' }
    try {
      const phrase = await ongeste(s, g)
      if (typeof phrase === 'string') messages = { ...messages, [s.id]: phrase }
    } catch (e) {
      messages = { ...messages, [s.id]: e?.message || String(e) }
    }
    enCours = { ...enCours, [s.id]: '' }
    await lire()
  }

  async function basculer(id) {
    ouvert = ouvert === id ? null : id
    if (ouvert) {
      await tick()
      ficheOuverte?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      ficheOuverte?.focus({ preventScroll: true })
    }
  }

  function clavier(e) {
    if (e.key === 'Escape' && ouvert) {
      const id = ouvert
      ouvert = null
      tick().then(() => document.getElementById('tuile-' + id)?.focus())
    }
  }

  const voyant = (etat) =>
    etat === 'repond' ? 'bg-primary' : etat === 'ne_repond_pas' ? 'bg-destructive' : etat === 'relie' ? 'bg-muted-foreground' : 'border-2 border-muted-foreground'

  onMount(lire)
</script>

<svelte:window onkeydown={clavier} />

<header class="mb-5">
  {#if etiquette}<p class="etiquette">{etiquette}</p>{/if}
  <h1 class="titre">{titre}</h1>
</header>

{#if erreur}<p class="mb-3 text-sm text-destructive" role="alert">{erreur}</p>{/if}

{#if reponse && !services.length}
  <p class="text-sm text-muted-foreground">Cette appli ne dépend d'aucun service extérieur.</p>
{:else if !enTuiles}
  <ul class="grid gap-3 sm:grid-cols-2" aria-label="Services">
    {#each services as s (s.id)}
      <li>
        <FicheService service={s} simule={reponse.simule} {lectureSeule} enCours={enCours[s.id] || ''} message={messages[s.id] || ''} annonce={annonces[s.id] || ''}
                      onverifier={verifier} ongeste={ongeste ? geste : null} />
      </li>
    {/each}
  </ul>
{:else}
  <ul class="grid grid-cols-2 gap-3 md:grid-cols-4" aria-label="Services">
    {#each services as s (s.id)}
      <li>
        <button
          type="button"
          id={'tuile-' + s.id}
          aria-expanded={ouvert === s.id}
          aria-controls="fiche-ouverte"
          onclick={() => basculer(s.id)}
          class="flex min-h-24 w-full flex-col gap-1.5 rounded-2xl border bg-card p-4 text-left transition-colors hover:border-primary aria-expanded:border-primary aria-expanded:ring-1 aria-expanded:ring-primary"
        >
          <span class="flex items-center gap-2">
            <span aria-hidden="true" class="size-2.5 shrink-0 rounded-full {voyant(s.etat)}"></span>
            <span class="font-medium leading-tight">{s.nom}</span>
          </span>
          <span class="text-sm {s.etat === 'ne_repond_pas' ? 'text-destructive' : 'text-muted-foreground'}">{MOTS[s.etat] ?? s.etat}</span>
        </button>
      </li>
    {/each}
  </ul>
  {#if choisi}
    <div id="fiche-ouverte" class="mt-4 scroll-mt-4 outline-none" tabindex="-1" bind:this={ficheOuverte}>
      <FicheService service={choisi} simule={reponse.simule} {lectureSeule} enCours={enCours[choisi.id] || ''}
                    message={messages[choisi.id] || ''} annonce={annonces[choisi.id] || ''} onverifier={verifier} ongeste={ongeste ? geste : null} />
    </div>
  {:else}
    <p class="mt-4 text-sm text-muted-foreground">Touche un service pour voir ce que l'appli y lit et y écrit.</p>
  {/if}
{/if}
<!-- empreinte: 33c19cc20d1f329f -->

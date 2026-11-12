<script>
  // Transhumance : outil d'une seule fois, piloté au PC. Deux entrées : Migrer (l'arbre) et Connexion.
  import { onMount } from 'svelte'
  import FolderTree from '@lucide/svelte/icons/folder-tree'
  import Network from '@lucide/svelte/icons/network'
  import { api } from '$lib/api.js'
  import Connexion from './pages/Connexion.svelte'
  import Migrer from './pages/Migrer.svelte'
  import Services from './pages/Services.svelte'

  const onglets = [
    { page: 'migrer', nom: 'Migrer', icone: FolderTree },
    { page: 'connexion', nom: 'Connexion', icone: Network },
  ]
  let connecte = $state(null)
  let session = $state({ version: '', lecture_seule: false })
  let page = $state(lirePage())
  function lirePage() {
    const p = location.hash.replace('#/', '')
    return onglets.some((o) => o.page === p) ? p : 'migrer'
  }
  async function verifier() {
    try { session = await api.get('/api/session'); connecte = session.connecte } catch { connecte = false }
  }
  async function deconnecter() {
    try { await api.post('/api/deconnexion') } catch { /* déjà fait */ }
    connecte = false
  }
  onMount(verifier)
</script>

<svelte:window onhashchange={() => (page = lirePage())} />

{#if connecte === false}
  <Connexion onconnecte={verifier} />
{:else if connecte}
  <div class="md:pl-52">
    <nav aria-label="Sections"
         class="flex items-center gap-1 border-b p-2 md:fixed md:inset-y-0 md:left-0 md:w-52 md:flex-col md:items-stretch md:border-b-0 md:border-r md:p-4">
      <span class="mr-3 px-2 text-xl font-light tracking-tight md:mb-4 md:mr-0">Transhumance</span>
      {#each onglets as o}
        {@const Icone = o.icone}
        <a href={'#/' + o.page} aria-label={o.nom} aria-current={page === o.page ? 'page' : undefined}
           class="flex h-10 items-center gap-2 rounded-lg px-3 text-sm font-medium text-muted-foreground hover:text-foreground aria-[current=page]:bg-secondary aria-[current=page]:text-foreground">
          <Icone class="size-[1.15rem]" aria-hidden="true" /><span>{o.nom}</span>
        </a>
      {/each}
    </nav>
    <main class="mx-auto max-w-5xl px-[max(1rem,env(safe-area-inset-left))] py-6 md:px-8 md:py-8">
      {#if session.lecture_seule}
        <p class="mb-4 rounded-xl border border-primary/50 px-4 py-2 text-sm" role="status">
          Mode lecture seule : Transhumance montre l'arbre et les bilans, n'envoie rien et ne supprime rien.</p>
      {/if}
      {#if page === 'connexion'}
        <Services {deconnecter} ondeconnecte={() => (connecte = false)} />
      {:else}
        <Migrer lectureSeule={session.lecture_seule} ondeconnecte={() => (connecte = false)} />
      {/if}
    </main>
  </div>
{/if}

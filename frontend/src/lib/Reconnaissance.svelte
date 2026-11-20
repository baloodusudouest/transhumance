<script>
  // 0.1.5 : qui fait la reconnaissance d'Immich (visages, recherche, texte) — le PC ou le NAS ?
  // Immich essaie ses adresses dans l'ordre ; Transhumance pose la même question à chacune, toutes les dix secondes.
  // 0.9.0 : seule la ligne courte (écran Migrer) reste ; le détail (adresses, files) est dans la fiche « PC de calcul »
  // de Connexion (guide, Réglages lus).
  import { onMount } from 'svelte'
  import { api } from '$lib/api.js'

  let { ondeconnecte } = $props()
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

<p class="mt-2 flex items-center gap-2 text-sm text-muted-foreground" id="reconnaissance-courte">
  <span class="size-2.5 flex-none rounded-full {r?.sur_pc ? 'bg-valide' : 'bg-muted-foreground/40'}" aria-hidden="true"></span>
  <span>{verdict}{r?.files?.length ? ` · ${reste} tâche(s) de reconnaissance en attente` : ''}</span></p>

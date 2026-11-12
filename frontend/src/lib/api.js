// Appels à l'API du kit. Une réponse 401 renvoie à l'écran de connexion.
export class ErreurApi extends Error {
  constructor(message, statut) {
    super(message)
    this.statut = statut
  }
}

async function repondre(r) {
  let donnees = null
  try { donnees = await r.json() } catch { /* réponse sans contenu */ }
  if (!r.ok) throw new ErreurApi(donnees?.detail || `Le serveur a répondu ${r.status}.`, r.status)
  return donnees
}

async function appel(methode, chemin, corps) {
  return repondre(await fetch(chemin, {
    method: methode,
    headers: corps ? { 'Content-Type': 'application/json' } : undefined,
    body: corps ? JSON.stringify(corps) : undefined,
    credentials: 'same-origin',
  }))
}

export const api = {
  get: (chemin) => appel('GET', chemin),
  post: (chemin, corps) => appel('POST', chemin, corps ?? {}),
  put: (chemin, corps) => appel('PUT', chemin, corps ?? {}),
  del: (chemin) => appel('DELETE', chemin),
  // Dépôt d'un fichier : il part tel quel dans le corps, ses renseignements dans l'adresse
  deposer: async (chemin, fichier, champs = {}) => {
    const q = new URLSearchParams({ nom: fichier.name, ...champs })
    return repondre(await fetch(`${chemin}?${q}`, {
      method: 'PUT', body: fichier, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/octet-stream' },
    }))
  },
}

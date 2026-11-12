export function poids(octets) {
  if (!octets) return '0'
  if (octets < 1024 ** 2) return `${Math.max(1, Math.round(octets / 1024))} ko`
  if (octets < 1024 ** 3) return `${(octets / 1024 ** 2).toFixed(0)} Mo`
  return `${(octets / 1024 ** 3).toFixed(1).replace('.', ',')} Go`
}
export function quand(iso) {
  if (!iso) return 'jamais'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? 'jamais' : d.toLocaleString('fr-FR', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
}

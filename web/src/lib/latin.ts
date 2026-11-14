/** "Wojakus vulgaris" becomes "W. vulgaris": the species epithet is the part that differs. */
export function abbreviateLatin(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length < 2) return name
  return `${parts[0]!.charAt(0)}. ${parts.slice(1).join(' ')}`
}

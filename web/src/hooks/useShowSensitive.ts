import { useSyncExternalStore } from 'react'

const STORAGE_KEY = 'memepedia:showSensitive'
const listeners = new Set<() => void>()

function readStored(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

let showSensitive = readStored()

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange)
  return () => listeners.delete(onChange)
}

function getSnapshot(): boolean {
  return showSensitive
}

/** Sets the global "show sensitive images" flag and persists it for next visit. */
export function setShowSensitive(value: boolean): void {
  showSensitive = value
  try {
    localStorage.setItem(STORAGE_KEY, String(value))
  } catch {
    // storage blocked (private mode, etc.) — keep the in-memory value only
  }
  listeners.forEach((listener) => listener())
}

/** The flag's current value, for code that fetches outside a render. */
export function getShowSensitive(): boolean {
  return showSensitive
}

/** Whether to show sensitive node images un-blurred everywhere, default off, persisted. */
export function useShowSensitive(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot)
}

// Small presentation helpers and fixed UI vocabulary. No story knowledge lives here: room names are the
// floor plan's labels, and the map rectangles are positions on art/plan/apartment-floor-plan.png.
import { useEffect, type RefObject } from 'react'
import type { Npc, Room } from '../protocol'

export const ROOM_NAME: Record<Room, string> = {
  outside: 'Outside',
  hall: 'Hall',
  living: 'Living room',
  kitchen: 'Kitchen',
  balcony: 'Balcony',
  bathroom: 'Bathroom',
}

export const PERSON_NAME: Record<Npc | 'leo', string> = { julian: 'Julian', mia: 'Mia', nora: 'Nora', leo: 'Leo' }

/** Rooms on the floor plan image, as percentages of its width and height. */
export const MAP_ROOMS: { room: Exclude<Room, 'outside'>; x: number; y: number; w: number; h: number }[] = [
  { room: 'balcony', x: 19, y: 13.5, w: 47, h: 9.5 },
  { room: 'living', x: 7, y: 22, w: 60, h: 36.5 },
  { room: 'kitchen', x: 69, y: 19.5, w: 24, h: 39 },
  { room: 'hall', x: 26, y: 63.5, w: 40, h: 18.5 },
  { room: 'bathroom', x: 7, y: 60, w: 17, h: 22 },
]

export const ADDRESSEES = ['julian', 'mia', 'both', 'nora', 'self'] as const

/** Close a popover on a press outside it or on Escape. */
export function useDismiss(ref: RefObject<HTMLElement | null>, open: boolean, onClose: () => void): void {
  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [ref, open, onClose])
}

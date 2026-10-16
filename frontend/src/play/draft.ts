import { create } from 'zustand'

/** Text another control asks to put in the box (the map, the phone drawer, the ringing phone). */
export const useDraft = create<{ prefill: string | null; put: (text: string) => void; take: () => string | null }>((set, get) => ({
  prefill: null,
  put: (text) => set({ prefill: text }),
  take: () => {
    const t = get().prefill
    set({ prefill: null })
    return t
  },
}))

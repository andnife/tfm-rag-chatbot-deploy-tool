import { create } from 'zustand'

interface SidebarState {
  open: boolean
  setOpen: (open: boolean) => void
  toggle: () => void
}

// Mobile drawer state. On desktop the sidebar is always visible regardless.
export const useSidebarStore = create<SidebarState>((set, get) => ({
  open: false,
  setOpen: (open) => set({ open }),
  toggle: () => set({ open: !get().open }),
}))

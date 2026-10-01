import { defineStore } from 'pinia'

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    shiftLabel: '白班 08:00-20:00',
    scope: '风电场机组运维平台',
    // 场站分档概览里选中的档位：离开概览再回来时保持不动。
    windfarmTier: 'all',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setWindfarmTier(key: string) {
      this.windfarmTier = key
    },
  },
})

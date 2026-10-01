<template>
  <section class="page" data-module="windfarm-overview">
    <header class="page-head">
      <div>
        <h2>场站分档概览</h2>
        <p class="page-desc">同一区域的场站并排归组，装机容量按当前口径分三档，逐档统计在建、运行中、限功率台数。</p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/windfarm">返回场站列表</RouterLink>
      </div>
    </header>

    <div class="tier-tabs">
      <button
        v-for="tab in tierTabs"
        :key="tab.key"
        class="tier-tab"
        :class="{ active: selectedTier === tab.key }"
        type="button"
        @click="selectTier(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <section class="config-panel">
      <div class="config-line">
        <span v-if="version">
          当前口径 <strong>{{ version.version }}</strong>（{{ version.生效日期 }} 生效）：{{ tierRangeText }}，装机容量缺失的场站归入「待补充」。
        </span>
        <button class="link" type="button" @click="toggleHistory">历史留档（{{ history.length }}）</button>
      </div>
      <form class="config-form" @submit.prevent="adjustTiers">
        <label class="filter-item">
          <span>下限（MW）</span>
          <input v-model="tierForm.lower" type="number" min="0" step="0.1" required />
        </label>
        <label class="filter-item">
          <span>上限（MW）</span>
          <input v-model="tierForm.upper" type="number" min="0" step="0.1" required />
        </label>
        <label class="filter-item">
          <span>备注</span>
          <input v-model="tierForm.remark" placeholder="本次调整说明" />
        </label>
        <button class="btn primary" type="submit">调整口径并重算</button>
      </form>
      <p v-if="configMessage" class="config-message">{{ configMessage }}</p>
      <div v-if="showHistory" class="history-list">
        <p v-if="!history.length" class="empty-state">暂无历史口径留档，首次调整口径后自动生成。</p>
        <article v-for="item in history" :key="item.version" class="history-item">
          <header>
            <strong>{{ item.version }}</strong>
            <span>{{ item.下限 }}–{{ item.上限 }}MW 口径 · {{ item.生效日期 }} 生效 · {{ item.归档时间 }} 留档</span>
          </header>
          <table class="data-table">
            <thead>
              <tr><th>场站编码</th><th>场站名称</th><th>所在区域</th><th>装机容量</th><th>当时档位</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in item.conclusions" :key="row.entry_id">
                <td>{{ row.场站编码 }}</td>
                <td>{{ row.场站名称 }}</td>
                <td>{{ row.所在区域 }}</td>
                <td>{{ row.装机容量 || '—' }}</td>
                <td>{{ tierLabel(row.档位) }}</td>
              </tr>
            </tbody>
          </table>
        </article>
      </div>
    </section>

    <div class="region-grid">
      <article
        v-for="region in regions"
        :key="region.name"
        class="region-card"
        :class="{ empty: !region.farms.length }"
      >
        <header class="region-head">
          <h3>{{ region.name }}</h3>
          <RouterLink
            v-if="region.farms.length"
            class="link"
            :to="{ path: '/windfarm', query: { region: region.name } }"
          >
            查看场站 →
          </RouterLink>
        </header>
        <p v-if="region.placeholder" class="placeholder-box">{{ region.placeholder }}</p>
        <template v-else>
          <div class="farm-chips">
            <span
              v-for="farm in visibleFarms(region)"
              :key="farm.id"
              class="farm-chip"
              :data-status="farm.status"
            >
              {{ farm.场站名称 }}
              <em>{{ farm.装机容量 || '容量待补充' }}</em>
            </span>
            <p v-if="!visibleFarms(region).length" class="empty-state">当前选中的档位下没有场站</p>
          </div>
          <table class="data-table tier-table">
            <thead>
              <tr><th>档位</th><th>场站数量</th><th>在建</th><th>运行中</th><th>限功率</th></tr>
            </thead>
            <tbody>
              <tr
                v-for="tier in tiers"
                :key="tier.key"
                :class="{ 'active-row': selectedTier === tier.key }"
              >
                <td>{{ tier.label }}</td>
                <td>{{ region.tiers[tier.key].场站数量 }}</td>
                <td>{{ region.tiers[tier.key].在建 }}</td>
                <td>{{ region.tiers[tier.key].运行中 }}</td>
                <td>{{ region.tiers[tier.key].限功率 }}</td>
              </tr>
            </tbody>
          </table>
        </template>
      </article>
    </div>

    <footer class="page-foot">
      <span>共 {{ regionCount }} 个区域 · 当前口径 {{ version?.version ?? '—' }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { fetchJson, request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

interface TierDef {
  key: string
  label: string
}

interface TierStats {
  场站数量: number
  在建: number
  运行中: number
  限功率: number
}

interface FarmItem {
  id: number
  场站编码: string
  场站名称: string
  装机容量: string | null
  容量MW: number | null
  status: string
  tier: string
}

interface RegionItem {
  name: string
  placeholder: string | null
  farms: FarmItem[]
  tiers: Record<string, TierStats>
}

interface TierVersion {
  version: string
  生效日期: string
  下限: number
  上限: number
  备注: string
}

interface OverviewPayload {
  version: TierVersion
  tiers: TierDef[]
  regions: RegionItem[]
}

interface HistoryItem extends TierVersion {
  归档时间: string
  conclusions: {
    entry_id: number
    场站编码: string
    场站名称: string
    所在区域: string
    装机容量: string | null
    容量MW: number | null
    档位: string
  }[]
}

const ENDPOINT = '/api/windfarm'
const ALL_TIERS = 'all'

const session = useSessionStore()

const version = ref<TierVersion | null>(null)
const tiers = ref<TierDef[]>([])
const regions = ref<RegionItem[]>([])
const history = ref<HistoryItem[]>([])
const showHistory = ref(false)
const errorMessage = ref('')
const configMessage = ref('')
const tierForm = reactive({ lower: '', upper: '', remark: '' })

const selectedTier = computed(() => session.windfarmTier)
const tierTabs = computed(() => [{ key: ALL_TIERS, label: '全部档位' }, ...tiers.value])
const tierRangeText = computed(() => tiers.value.slice(0, 3).map((tier) => tier.label).join(' / '))
const regionCount = computed(() => regions.value.length)

function selectTier(key: string) {
  session.setWindfarmTier(key)
}

function tierLabel(key: string) {
  return tiers.value.find((tier) => tier.key === key)?.label ?? key
}

function visibleFarms(region: RegionItem) {
  if (selectedTier.value === ALL_TIERS) {
    return region.farms
  }
  return region.farms.filter((farm) => farm.tier === selectedTier.value)
}

async function toggleHistory() {
  showHistory.value = !showHistory.value
  if (showHistory.value) {
    await loadHistory()
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await fetchJson<OverviewPayload>(`${ENDPOINT}/overview`)
    version.value = payload.version
    tiers.value = payload.tiers
    regions.value = payload.regions
    tierForm.lower = String(payload.version.下限)
    tierForm.upper = String(payload.version.上限)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分档概览读取失败'
  }
}

async function loadHistory() {
  try {
    const payload = await fetchJson<{ items: HistoryItem[] }>(`${ENDPOINT}/tier-history`)
    history.value = payload.items
  } catch {
    history.value = []
  }
}

async function adjustTiers() {
  configMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/tiers`, {
      method: 'POST',
      body: JSON.stringify({
        values: { 下限: tierForm.lower, 上限: tierForm.upper, 备注: tierForm.remark },
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? payload.detail ?? '分档口径调整失败')
    }
    configMessage.value = payload.message
    tierForm.remark = ''
    await Promise.all([reload(), loadHistory()])
  } catch (error) {
    configMessage.value = error instanceof Error ? error.message : '分档口径调整失败'
  }
}

onMounted(async () => {
  await Promise.all([reload(), loadHistory()])
})
</script>

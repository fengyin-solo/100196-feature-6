<template>
  <section class="page" data-module="windfarm">
    <header class="page-head">
      <div>
        <h2>风电场站管理</h2>
        <p class="page-desc">维护风电场站，围绕场站编码、场站名称、所在区域、装机容量做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记风电场站</button>
        <button class="btn" type="button" @click="exportRows">导出风电场站清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="view-tabs" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        role="tab"
        :class="['tab-btn', { active: activeTab === tab.key }]"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
      </button>
      <button
        v-if="activeTab === 'list' && (filters.region || filters.bucket)"
        type="button"
        class="link clear-drill"
        @click="clearDrillFilters"
      >
        清除「{{ drillScopeLabel }}」下钻条件 ×
      </button>
    </div>

    <!-- 区域 × 装机容量概览 -->
    <div v-show="activeTab === 'overview'" class="overview-pane">
      <div v-if="overviewLoading" class="pane-tip">概览加载中…</div>
      <template v-else-if="overview">
        <div class="version-banner">
          <div class="version-info">
            <span class="version-tag">{{ overview.version.code }}</span>
            <span>当前分档口径：&lt; {{ overview.version.thresholds[0] }}MW /
              {{ overview.version.thresholds[0] }}–{{ overview.version.thresholds[1] }}MW /
              ≥ {{ overview.version.thresholds[1] }}MW，装机容量缺失归入「待补充」</span>
            <span class="version-time">生效时间 {{ overview.version.updated_at }}</span>
          </div>
          <button type="button" class="btn" @click="openAdjust">调整分档口径</button>
        </div>

        <form v-if="adjustOpen" class="adjust-panel" @submit.prevent="submitAdjust">
          <h4>调整装机容量分档口径</h4>
          <p class="panel-hint">
            提交后立即生成新版本，存量场站按新口径重算分档；原口径结论整版留档，可在下方历史版本回看。
          </p>
          <div class="adjust-fields">
            <label>
              <span>小型 / 中型分界（MW）</span>
              <input v-model.number="adjustForm.low" type="number" min="1" step="0.1" required />
            </label>
            <label>
              <span>中型 / 大型分界（MW）</span>
              <input v-model.number="adjustForm.high" type="number" min="1" step="0.1" required />
            </label>
            <label class="adjust-remark">
              <span>调整说明</span>
              <input v-model="adjustForm.remark" placeholder="例如：按大兆瓦机组普及上调分界" />
            </label>
          </div>
          <div class="adjust-actions">
            <button class="btn primary" type="submit" :disabled="adjusting">
              {{ adjusting ? '重算中…' : '提交并重算存量场站' }}
            </button>
            <button class="btn ghost" type="button" @click="adjustOpen = false">取消</button>
          </div>
        </form>

        <table class="matrix-table">
          <thead>
            <tr>
              <th class="region-col">所在区域</th>
              <th v-for="bucket in overview.buckets" :key="bucket.key" class="bucket-col">
                <button
                  type="button"
                  :class="['bucket-head', { selected: selectedBucket === bucket.key }]"
                  @click="selectBucket(bucket.key)"
                >
                  {{ bucket.label }}
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="region in overview.regions" :key="region.region">
              <th class="region-cell">
                <span class="region-name">{{ region.region }}</span>
                <span class="region-total">共 {{ region.stations }} 个场站</span>
              </th>
              <td
                v-for="cell in region.cells"
                :key="cell.bucket"
                :class="[
                  'matrix-cell',
                  { clickable: cell.count > 0, dimmed: selectedBucket && selectedBucket !== cell.bucket },
                ]"
                @click="cell.count > 0 && drillInto(region.region, cell.bucket)"
              >
                <template v-if="cell.count > 0">
                  <strong class="cell-count">{{ cell.count }}</strong>
                  <span class="cell-unit">个场站</span>
                  <ul class="status-line">
                    <li v-for="status in trackedStatuses" :key="status">
                      <em :class="['status-dot', statusClass(status)]">{{ status }}</em>
                      <b>{{ cell.statuses[status] ?? 0 }}</b>
                    </li>
                  </ul>
                </template>
                <span v-else-if="region.empty" class="cell-placeholder">区域暂无场站，待登记</span>
                <span v-else class="cell-placeholder">该档位暂无场站</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="matrix-legend">
          点击格子可下钻到对应区域、档位的场站清单；点击表头档位可高亮关注，重新进入概览时保持选中。
        </p>

        <section class="history-panel">
          <h4>历史分档口径留档</h4>
          <p v-if="!archives.length" class="panel-hint">尚未调整过分档口径，暂无历史版本。</p>
          <ul v-else class="archive-list">
            <li v-for="archive in archives" :key="archive.id" class="archive-item">
              <div class="archive-head">
                <button type="button" class="link" @click="toggleArchive(archive.id)">
                  {{ expandedArchive === archive.id ? '▾' : '▸' }} {{ archive.version_code }}
                </button>
                <span class="archive-meta">
                  分界 {{ archive.thresholds[0] }} / {{ archive.thresholds[1] }} MW ·
                  留档于 {{ archive.archived_at }} · 被 {{ archive.superseded_by }} 替代
                </span>
                <span v-if="archive.remark" class="archive-remark">{{ archive.remark }}</span>
              </div>
              <div v-if="expandedArchive === archive.id" class="archive-body">
                <p v-if="archiveLoading" class="panel-hint">留档明细加载中…</p>
                <table v-else-if="archiveDetail" class="snapshot-table">
                  <thead>
                    <tr>
                      <th>区域</th>
                      <th v-for="cell in archiveDetail.regions[0]?.cells ?? []" :key="cell.bucket">
                        {{ cell.label }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="region in archiveDetail.regions" :key="region.region">
                      <th>{{ region.region }}</th>
                      <td
                        v-for="cell in region.cells"
                        :key="cell.bucket"
                        :class="{ clickable: cell.count > 0 }"
                        @click="cell.count > 0 && drillInto(region.region, cell.bucket)"
                      >
                        <template v-if="cell.count > 0">
                          <strong>{{ cell.count }}</strong> 个
                          <ul class="snapshot-status">
                            <li v-for="station in cell.stations" :key="station.id">
                              {{ station.场站名称 }}（{{ station.status }}）
                            </li>
                          </ul>
                        </template>
                        <span v-else class="cell-placeholder">—</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
                <p v-else class="panel-hint">留档明细读取失败，请稍后重试。</p>
                <p class="panel-hint">历史结论只按当时版本展示，不会随后续口径调整改变。</p>
              </div>
            </li>
          </ul>
        </section>
      </template>
      <div v-else class="pane-tip">概览读取失败，可稍后重试。</div>
    </div>

    <!-- 场站清单 -->
    <div v-show="activeTab === 'list'" class="list-pane">
      <form class="filter-bar" @submit.prevent="reload">
        <label class="filter-item">
          <span>场站编码</span>
          <input v-model="filters.keyword" placeholder="按场站编码检索" />
        </label>
        <label class="filter-item">
          <span>所在区域</span>
          <input v-model="filters.region" list="region-options" placeholder="按所在区域检索" />
          <datalist id="region-options">
            <option v-for="region in regionOptions" :key="region" :value="region" />
          </datalist>
        </label>
        <label class="filter-item">
          <span>场站状态</span>
          <select v-model="filters.status">
            <option value="">全部状态</option>
            <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>装机容量档位</span>
          <select v-model="filters.bucket">
            <option value="">全部档位</option>
            <option v-for="bucket in bucketOptions" :key="bucket.key" :value="bucket.key">
              {{ bucket.label }}
            </option>
          </select>
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)">
            <td v-for="column in columns" :key="column">{{ displayValue(row, column) }}</td>
            <td class="row-actions">
              <button
                v-for="action in actions"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 1" class="empty-state">暂无符合条件的风电场站</td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条风电场站记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type BucketKey = 'small' | 'medium' | 'large' | 'pending'

type OverviewCell = {
  bucket: BucketKey
  label: string
  count: number
  statuses: Record<string, number>
}
type OverviewRegion = {
  region: string
  stations: number
  empty: boolean
  cells: OverviewCell[]
}
type Overview = {
  version: { code: string; thresholds: number[]; updated_at: string; remark?: string }
  buckets: { key: BucketKey; label: string }[]
  regions: OverviewRegion[]
}
type ArchiveSummary = {
  id: number
  version_code: string
  thresholds: number[]
  archived_at: string
  superseded_by: string
  remark?: string
}
type ArchiveDetail = {
  id: number
  version_code: string
  thresholds: number[]
  archived_at: string
  superseded_by: string
  regions: (OverviewRegion & {
    cells: (OverviewCell & {
      stations: { id: number; 场站名称: string; status: string }[]
    })[]
  })[]
}

const ENDPOINT = '/api/windfarm'
const BUCKET_STORAGE_KEY = 'windfarm:overview:bucket'
const columns = ['场站编码', '场站名称', '所在区域', '装机容量', '并网日期', '运营单位', '海拔高度', '场站状态']
const actions = ['并网投运', '申请限功率', '转入检修']
const statuses = ['在建', '运行中', '限功率', '停运检修']
const trackedStatuses = ['在建', '运行中', '限功率']
const regionOptions = ['华北', '东北', '华东', '华中', '西北', '西南', '华南']
const tabs = [
  { key: 'overview', label: '区域容量概览' },
  { key: 'list', label: '场站清单' },
] as const
type TabKey = (typeof tabs)[number]['key']

const activeTab = ref<TabKey>('overview')
const overview = ref<Overview | null>(null)
const overviewLoading = ref(false)
const overviewLoaded = ref(false)
const archives = ref<ArchiveSummary[]>([])
const expandedArchive = ref<number | null>(null)
const archiveDetail = ref<ArchiveDetail | null>(null)
const archiveLoading = ref(false)

const selectedBucket = ref<BucketKey | ''>('')
const adjustOpen = ref(false)
const adjusting = ref(false)
const adjustForm = reactive({ low: 50, high: 200, remark: '' })

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = reactive<{ keyword: string; region: string; status: string; bucket: BucketKey | '' }>({
  keyword: '',
  region: '',
  status: '',
  bucket: '',
})

const stats = computed(() => {
  if (!overview.value) {
    return [
      { label: '场站总数', value: total.value },
      { label: '运行中', value: 0 },
      { label: '限功率', value: 0 },
      { label: '容量待补充', value: 0 },
    ]
  }
  let running = 0
  let curtailed = 0
  let pending = 0
  for (const region of overview.value.regions) {
    for (const cell of region.cells) {
      running += cell.statuses['运行中'] ?? 0
      curtailed += cell.statuses['限功率'] ?? 0
      if (cell.bucket === 'pending') pending += cell.count
    }
  }
  const stations = overview.value.regions.reduce((sum, region) => sum + region.stations, 0)
  return [
    { label: '场站总数', value: stations },
    { label: '运行中', value: running },
    { label: '限功率', value: curtailed },
    { label: '容量待补充', value: pending },
  ]
})

const bucketOptions = computed(() => overview.value?.buckets ?? [])

const drillScopeLabel = computed(() => {
  const parts: string[] = []
  if (filters.region) parts.push(filters.region)
  if (filters.bucket) {
    const label = bucketOptions.value.find((item) => item.key === filters.bucket)?.label
    parts.push(label ?? filters.bucket)
  }
  return parts.join(' · ')
})

function statusClass(status: string) {
  return {
    'is-building': status === '在建',
    'is-running': status === '运行中',
    'is-curtailed': status === '限功率',
  }
}

function displayValue(row: Row, column: string) {
  if (column === '场站状态') return row.status ?? row[column] ?? '—'
  return row[column] ?? '—'
}

function selectBucket(key: BucketKey) {
  // 再点一次取消选中；选择落到 localStorage，重新进入概览也能保持
  selectedBucket.value = selectedBucket.value === key ? '' : key
  if (selectedBucket.value) {
    window.localStorage.setItem(BUCKET_STORAGE_KEY, selectedBucket.value)
  } else {
    window.localStorage.removeItem(BUCKET_STORAGE_KEY)
  }
}

function restoreSelectedBucket() {
  const saved = window.localStorage.getItem(BUCKET_STORAGE_KEY)
  if (saved === 'small' || saved === 'medium' || saved === 'large' || saved === 'pending') {
    selectedBucket.value = saved
  }
}

function switchTab(key: TabKey) {
  activeTab.value = key
  if (key === 'overview') {
    void loadOverview()
  } else {
    void reload()
  }
}

async function loadOverview() {
  overviewLoading.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/overview`)
    if (!response.ok) throw new Error('区域容量概览读取失败')
    overview.value = await response.json()
    overviewLoaded.value = true
    const versionsResponse = await request(`${ENDPOINT}/tiers`)
    if (versionsResponse.ok) {
      const payload = await versionsResponse.json()
      archives.value = payload.archives ?? []
      if (!selectedBucket.value) {
        adjustForm.low = Number(payload.thresholds?.[0] ?? 50)
        adjustForm.high = Number(payload.thresholds?.[1] ?? 200)
      }
    }
  } catch (error) {
    overview.value = null
    errorMessage.value = error instanceof Error ? error.message : '区域容量概览读取失败'
  } finally {
    overviewLoading.value = false
  }
}

function openAdjust() {
  if (overview.value) {
    adjustForm.low = overview.value.version.thresholds[0]
    adjustForm.high = overview.value.version.thresholds[1]
  }
  adjustForm.remark = ''
  adjustOpen.value = true
}

async function submitAdjust() {
  errorMessage.value = ''
  adjusting.value = true
  try {
    const response = await request(`${ENDPOINT}/tiers/adjust`, {
      method: 'POST',
      body: JSON.stringify({ thresholds: [adjustForm.low, adjustForm.high], remark: adjustForm.remark }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '分档口径调整失败')
    }
    adjustOpen.value = false
    expandedArchive.value = null
    archiveDetail.value = null
    await loadOverview()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分档口径调整失败'
  } finally {
    adjusting.value = false
  }
}

async function toggleArchive(archiveId: number) {
  if (expandedArchive.value === archiveId) {
    expandedArchive.value = null
    archiveDetail.value = null
    return
  }
  expandedArchive.value = archiveId
  archiveDetail.value = null
  archiveLoading.value = true
  try {
    const response = await request(`${ENDPOINT}/tiers/archives/${archiveId}`)
    if (!response.ok) throw new Error('历史留档读取失败')
    archiveDetail.value = await response.json()
  } catch (error) {
    archiveDetail.value = null
    errorMessage.value = error instanceof Error ? error.message : '历史留档读取失败'
  } finally {
    archiveLoading.value = false
  }
}

function drillInto(region: string, bucket: BucketKey) {
  // 概览点进某个区域/档位，直接落到对应场站
  filters.region = region
  filters.bucket = bucket
  activeTab.value = 'list'
  void reload()
}

function clearDrillFilters() {
  filters.region = ''
  filters.bucket = ''
  void reload()
}

function resetFilters() {
  filters.keyword = ''
  filters.region = ''
  filters.status = ''
  filters.bucket = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '风电场站登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('风电场站动作未生效，请稍后重试')
    }
    await reload()
    await loadOverview()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '风电场站操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.region) query.set('region', filters.region)
  if (filters.status) query.set('status', filters.status)
  if (filters.bucket) query.set('bucket', filters.bucket)
  query.set('size', '200')
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('风电场站列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '风电场站列表读取失败'
  }
}

onMounted(() => {
  restoreSelectedBucket()
  void loadOverview()
})
</script>

<style scoped>
.view-tabs {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0 12px;
  border-bottom: 1px solid var(--border);
}
.tab-btn {
  border: none;
  background: none;
  padding: 8px 14px;
  font-size: 14px;
  color: var(--muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}
.tab-btn.active {
  color: var(--brand);
  border-bottom-color: var(--brand);
  font-weight: 600;
}
.clear-drill {
  margin-left: auto;
  font-size: 12px;
}
.version-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-left: 3px solid var(--brand);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 12px;
  font-size: 13px;
}
.version-info {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.version-tag {
  background: var(--brand);
  color: #fff;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 12px;
  font-weight: 600;
}
.version-time {
  color: var(--muted);
  font-size: 12px;
}
.adjust-panel,
.history-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;
}
.adjust-panel h4,
.history-panel h4 {
  margin: 0 0 6px;
  font-size: 14px;
}
.panel-hint {
  color: var(--muted);
  font-size: 12px;
  margin: 4px 0;
}
.adjust-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.adjust-fields label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
}
.adjust-fields input {
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
  width: 180px;
}
.adjust-fields .adjust-remark input {
  width: 280px;
}
.adjust-actions {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}
.matrix-table,
.snapshot-table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
  border: 1px solid var(--border);
}
.matrix-table th,
.matrix-table td,
.snapshot-table th,
.snapshot-table td {
  border: 1px solid var(--border);
  padding: 10px 12px;
  font-size: 13px;
  text-align: left;
  vertical-align: top;
}
.region-col,
.bucket-col {
  background: #f1f5f9;
}
.bucket-head {
  border: none;
  background: none;
  padding: 0;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  color: #1f2937;
}
.bucket-head.selected {
  color: var(--brand);
}
.bucket-head.selected::after {
  content: ' ✓';
}
.region-cell {
  min-width: 120px;
}
.region-name {
  display: block;
  font-weight: 600;
}
.region-total {
  display: block;
  color: var(--muted);
  font-size: 12px;
  font-weight: 400;
  margin-top: 2px;
}
.matrix-cell {
  min-width: 150px;
}
.matrix-cell.clickable {
  cursor: pointer;
}
.matrix-cell.clickable:hover {
  background: #eff6ff;
}
.matrix-cell.dimmed {
  opacity: 0.45;
}
.cell-count {
  font-size: 22px;
  color: var(--brand);
}
.cell-unit {
  color: var(--muted);
  font-size: 12px;
  margin-left: 4px;
}
.status-line {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.status-line li {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
}
.status-dot {
  font-style: normal;
  border-radius: 4px;
  padding: 1px 6px;
  color: #fff;
  font-size: 11px;
}
.status-dot.is-building { background: #b0862a; }
.status-dot.is-running { background: #1a7f4e; }
.status-dot.is-curtailed { background: #b4531a; }
.cell-placeholder {
  color: var(--muted);
  font-size: 12px;
}
.matrix-legend {
  color: var(--muted);
  font-size: 12px;
  margin: 6px 0 0;
}
.archive-list {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.archive-item {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
}
.archive-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 13px;
}
.archive-meta {
  color: var(--muted);
  font-size: 12px;
}
.archive-remark {
  font-size: 12px;
  color: #475569;
  background: #f8fafc;
  border-radius: 4px;
  padding: 1px 8px;
}
.archive-body {
  margin-top: 8px;
}
.snapshot-table {
  font-size: 12px;
}
.snapshot-status {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  color: var(--muted);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.snapshot-table td.clickable {
  cursor: pointer;
}
.snapshot-table td.clickable:hover {
  background: #eff6ff;
}
.pane-tip {
  padding: 24px;
  text-align: center;
  color: var(--muted);
  background: #fff;
  border: 1px dashed var(--border);
  border-radius: 8px;
}
.filter-item select {
  padding: 5px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
  min-width: 130px;
}
</style>

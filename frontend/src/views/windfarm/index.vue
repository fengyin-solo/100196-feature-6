<template>
  <section class="page" data-module="windfarm">
    <header class="page-head">
      <div>
        <h2>风电场站管理</h2>
        <p class="page-desc">维护风电场站，围绕场站编码、场站名称、所在区域、装机容量做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/windfarm/overview">分档概览</RouterLink>
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

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="regionFilter" class="region-chip">
      已按区域过滤：{{ regionFilter }}
      <button class="link" type="button" @click="clearRegion">清除</button>
    </p>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无风电场站数据，可先登记风电场站</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条风电场站记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/windfarm'
const columns = ["场站编码", "场站名称", "所在区域", "装机容量", "并网日期", "运营单位", "海拔高度", "场站状态"]
const actions = ["并网投运", "申请限功率", "转入检修"]
const statuses = ["在建", "运行中", "限功率", "停运检修"]
const stats = [{"label": "在运场站", "value": 0}, {"label": "装机容量", "value": 0}, {"label": "限功率场站", "value": 0}]

const route = useRoute()
const router = useRouter()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const regionFilter = computed(() => (filters.value['所在区域'] ?? '').trim())

function resetFilters() {
  filters.value = {}
  void reload()
}

function clearRegion() {
  filters.value = { ...filters.value, 所在区域: '' }
  void router.replace({ query: {} })
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
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '风电场站操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  for (const [field, value] of Object.entries(filters.value)) {
    const keyword = value.trim()
    if (!keyword) {
      continue
    }
    if (field === '场站编码') {
      query.set('keyword', keyword)
    } else if (field === '所在区域') {
      query.set('region', keyword)
    } else {
      query.set(field, keyword)
    }
  }
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
  const region = route.query.region
  if (typeof region === 'string' && region.trim()) {
    filters.value = { ...filters.value, 所在区域: region.trim() }
  }
  void reload()
})
</script>

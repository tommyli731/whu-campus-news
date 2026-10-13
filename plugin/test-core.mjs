/**
 * 插件核心逻辑独立测试
 * 不依赖 Cordis/DSH，直接验证 API 调用与渲染逻辑
 */
const API_BASE = 'https://whu-campus-news.app.workbuddy.host'
const TIMEOUT_MS = 15000

const CATEGORY_LABEL = {
  headline: '要闻速览', academic: '学术讲座', notice: '通知公告',
  college: '院系动态', activity: '文体活动', party: '党团思政',
}
const LEVEL_LABEL = { S: '重要', A: '较重要', B: '常规' }
const AUDIENCE_LABEL = { stu: '仅学生', tea: '仅教师', both: '师生通用' }

async function callApi(path, params = {}, signal) {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') qs.set(k, String(v))
  }
  const url = `${API_BASE}${path}${qs.toString() ? '?' + qs : ''}`
  const res = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.any([signal, AbortSignal.timeout(TIMEOUT_MS)]),
  })
  if (!res.ok) {
    let detail = ''
    try {
      const body = await res.json()
      detail = body.error?.message ?? ''
    } catch {}
    throw new Error(`接口返回 ${res.status}${detail ? '：' + detail : ''}`)
  }
  const json = await res.json()
  if (!json.success || json.data === undefined) {
    throw new Error(json.error?.message ?? '接口返回失败')
  }
  return json.data
}

function renderNoticeList(items, updatedAt, total) {
  if (items.length === 0) {
    return `未找到符合条件的资讯（共 ${total} 条符合条件）。\n可尝试放宽筛选条件，或用不同关键词搜索。`
  }
  const lines = items.map((n, i) => {
    return [
      `${i + 1}. 【${n.category_label}】${n.title}`,
      `   日期：${n.date}　重要度：${LEVEL_LABEL[n.level] ?? n.level}　受众：${AUDIENCE_LABEL[n.audience] ?? n.audience}`,
      `   来源：${n.source_name}${n.source_column ? ' · ' + n.source_column : ''}`,
      `   摘要：${n.summary || '（无摘要）'}`,
      `   原文：${n.url}`,
    ].join('\n')
  })
  const header = `共找到 ${total} 条资讯${items.length < total ? `，显示前 ${items.length} 条` : ''}。`
  const footer = updatedAt ? `\n数据更新时间：${updatedAt}（每日自动采集）` : ''
  return header + '\n\n' + lines.join('\n\n') + footer
}

;(async () => {
  console.log('='.repeat(60))
  console.log('插件核心逻辑测试')
  console.log('='.repeat(60))
  const sig = AbortSignal.timeout(20000)
  let pass = 0, fail = 0

  // 工具1：浏览资讯
  console.log('\n【工具1】whu_notices — 浏览校园资讯')
  try {
    const d = await callApi('/api/notices', { page_size: 10, sort: 'date_desc' }, sig)
    console.log(`  ✅ 调用成功，${d.total} 条可用，返回 ${d.items.length} 条`)
    console.log('\n--- 模型看到的文本输出 ---')
    console.log(renderNoticeList(d.items, d.data_updated_at, d.total).slice(0, 700))
    console.log('--- 结束 ---')
    pass++
  } catch (e) { console.log('  ❌', e.message); fail++ }

  // 工具1b：分类筛选
  console.log('\n【工具1b】带筛选：通知公告 + S级')
  try {
    const d = await callApi('/api/notices', { category: 'notice', level: 'S', page_size: 5 }, sig)
    console.log(`  ✅ 通知公告+重要 → ${d.total} 条`)
    d.items.forEach(n => console.log(`     ${n.date} 【${n.category_label}】${n.title.slice(0, 36)}`))
    pass++
  } catch (e) { console.log('  ❌', e.message); fail++ }

  // 工具1c：最近7天
  console.log('\n【工具1c】days=7（最近一周）')
  try {
    const dt = new Date(); dt.setDate(dt.getDate() - 7)
    const since = dt.toISOString().slice(0, 10)
    const d = await callApi('/api/notices', { since, page_size: 20 }, sig)
    console.log(`  ✅ ${since} 以来 ${d.total} 条`)
    pass++
  } catch (e) { console.log('  ❌', e.message); fail++ }

  // 工具2：搜索
  console.log('\n【工具2】whu_search — 关键词搜索')
  try {
    const d = await callApi('/api/search', { q: '讲座', page_size: 5 }, sig)
    console.log(`  ✅ 搜索"讲座" → ${d.total} 条`)
    console.log('\n--- 模型看到的文本输出 ---')
    console.log(renderNoticeList(d.items, null, d.total).slice(0, 400))
    console.log('--- 结束 ---')
    pass++
  } catch (e) { console.log('  ❌', e.message); fail++ }

  // 工具2b：空结果
  console.log('\n【工具2b】搜索无结果时的降级文案')
  try {
    const d = await callApi('/api/search', { q: 'zzz不存在的词xyz' }, sig)
    console.log('  ✅ 空结果文案：')
    console.log('    ' + renderNoticeList(d.items, null, d.total).split('\n')[0])
    pass++
  } catch (e) { console.log('  ❌', e.message); fail++ }

  // 工具3：详情
  console.log('\n【工具3】whu_notice_detail — 详情')
  try {
    const list = await callApi('/api/notices', { page_size: 1 }, sig)
    const id = list.items[0].id
    const n = await callApi(`/api/notices/${encodeURIComponent(id)}`, {}, sig)
    console.log(`  ✅ 详情获取成功：${n.title.slice(0, 40)}`)
    console.log(`     发布机构：${n.publisher}`)
    console.log(`     作者：${n.author}`)
    console.log(`     正文长度：${(n.content || '').length} 字符`)
    pass++
  } catch (e) { console.log('  ❌', e.message); fail++ }

  // 工具4：概览
  console.log('\n【工具4】whu_news_overview — 概览')
  try {
    const [stats, sources] = await Promise.all([
      callApi('/api/stats', {}, sig),
      callApi('/api/sources', {}, sig),
    ])
    console.log(`  ✅ 总数 ${stats.total} 条，区间 ${stats.date_range?.from}~${stats.date_range?.to}`)
    console.log(`     分类：${stats.by_category.map(c => c.label + ':' + c.count).join(', ')}`)
    console.log(`     来源渠道：${sources.items.map(s => s.name + ':' + s.item_count).join(', ')}`)
    pass++
  } catch (e) { console.log('  ❌', e.message); fail++ }

  console.log('\n' + '='.repeat(60))
  console.log(`结果：${pass} 通过 / ${fail} 失败`)
  console.log('='.repeat(60))
  process.exit(fail > 0 ? 1 : 0)
})()
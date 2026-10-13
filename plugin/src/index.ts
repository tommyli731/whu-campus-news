/**
 * dsh-plugin-whu-news
 *
 * 武汉大学校园资讯查询插件。
 *
 * 依赖线上公开 API：
 *   https://whu-campus-news.app.workbuddy.host
 *
 * 数据每日 08:00 与 18:00（北京时间）由 GitHub Actions 自动采集更新。
 */

import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'whu-news'

export const inject = ['tools']

/** API 根地址，可用环境变量覆盖 */
const API_BASE =
  (typeof process !== 'undefined' && process.env?.WHU_NEWS_API) ||
  'https://whu-campus-news.app.workbuddy.host'

/** 单次请求超时（毫秒） */
const TIMEOUT_MS = 15_000

const CATEGORY_LABEL: Record<string, string> = {
  headline: '要闻速览',
  academic: '学术讲座',
  notice: '通知公告',
  college: '院系动态',
  activity: '文体活动',
  party: '党团思政',
}

const LEVEL_LABEL: Record<string, string> = {
  S: '重要',
  A: '较重要',
  B: '常规',
}

const AUDIENCE_LABEL: Record<string, string> = {
  stu: '仅学生',
  tea: '仅教师',
  both: '师生通用',
}

interface NoticeItem {
  id: string
  title: string
  date: string
  category: string
  category_label: string
  level: string
  audience: string
  source_name: string
  source_column: string
  summary: string
  url: string
}

interface NoticeDetail extends NoticeItem {
  content: string
  publisher: string
  author: string
}

/** 调用 API 并处理错误 */
async function callApi<T>(path: string, params: Record<string, string | number | undefined>, signal: AbortSignal): Promise<T> {
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
      const body = (await res.json()) as { error?: { message?: string } }
      detail = body.error?.message ?? ''
    } catch {
      /* 响应体不是 JSON 时忽略 */
    }
    throw new Error(`接口返回 ${res.status}${detail ? '：' + detail : ''}`)
  }

  const json = (await res.json()) as {
    success: boolean
    data?: T
    error?: { message?: string }
  }
  if (!json.success || json.data === undefined) {
    throw new Error(json.error?.message ?? '接口返回失败')
  }
  return json.data
}

/** 把资讯列表格式化为模型易读的文字 */
function renderNoticeList(items: NoticeItem[], updatedAt: string | null, total: number): string {
  if (items.length === 0) {
    return `未找到符合条件的资讯（共 ${total} 条符合条件）。\n可尝试放宽筛选条件，或用不同关键词搜索。`
  }

  const lines = items.map((n, i) => {
    const parts = [
      `${i + 1}. 【${n.category_label}】${n.title}`,
      `   日期：${n.date}　重要度：${LEVEL_LABEL[n.level] ?? n.level}　受众：${AUDIENCE_LABEL[n.audience] ?? n.audience}`,
      `   来源：${n.source_name}${n.source_column ? ' · ' + n.source_column : ''}`,
      `   摘要：${n.summary || '（无摘要）'}`,
      `   原文：${n.url}`,
    ]
    return parts.join('\n')
  })

  const header = `共找到 ${total} 条资讯${items.length < total ? `，显示前 ${items.length} 条` : ''}。`
  const footer = updatedAt ? `\n数据更新时间：${updatedAt}（每日自动采集）` : ''
  return header + '\n\n' + lines.join('\n\n') + footer
}

export function apply(ctx: Context) {
  // ── 工具 1：浏览校园资讯 ──────────────────────────────
  ctx.tools.register(
    defineTool({
      name: 'whu_notices',
      description:
        '查询武汉大学校园资讯（通知公告、学术讲座、要闻、院系动态、文体活动、党团思政）。' +
        '当用户询问"最近有什么通知/讲座/活动"、"校园有什么消息"、"有没有重要的公告"时使用。' +
        '数据每日自动从学校官网采集更新。',
      parameters: {
        category: {
          type: 'string',
          description:
            '分类筛选。notice=通知公告，academic=学术讲座，headline=要闻速览，college=院系动态，activity=文体活动，party=党团思政。不填则返回全部。',
        },
        audience: {
          type: 'string',
          description:
            '受众筛选。stu=与学生相关，tea=与教师相关，both=仅师生通用。不填则返回全部。',
        },
        level: {
          type: 'string',
          description: '重要度筛选。S=重要，A=较重要，B=常规。不填则返回全部。',
        },
        days: {
          type: 'number',
          description: '只看最近多少天的资讯。例如填 7 表示最近一周。不填则不限。',
        },
        limit: {
          type: 'number',
          description: '返回条数，默认 10，最大 30。',
        },
      },
      output: {
        schema: { type: 'object' },
        render: (_args, value) => [{ type: 'text', text: value.text }],
      },
      async execute(args, exec) {
        let since: string | undefined
        if (args.days && args.days > 0) {
          const d = new Date()
          d.setDate(d.getDate() - Math.floor(args.days))
          since = d.toISOString().slice(0, 10)
        }

        const data = await callApi<{
          total: number
          items: NoticeItem[]
          data_updated_at: string | null
        }>(
          '/api/notices',
          {
            category: args.category,
            audience: args.audience,
            level: args.level,
            since,
            page_size: Math.min(args.limit ?? 10, 30),
            sort: 'date_desc',
          },
          exec.signal,
        )

        const text = renderNoticeList(data.items, data.data_updated_at, data.total)
        return {
          text,
          total: data.total,
          returned: data.items.length,
          updatedAt: data.data_updated_at,
          notices: data.items.map(n => ({
            id: n.id,
            title: n.title,
            date: n.date,
            category: n.category_label,
            url: n.url,
          })),
        }
      },
    }),
  )

  // ── 工具 2：关键词搜索 ────────────────────────────────
  ctx.tools.register(
    defineTool({
      name: 'whu_search',
      description:
        '按关键词搜索武汉大学校园资讯全文（标题、摘要、正文、发布机构、作者、栏目、来源）。' +
        '当用户明确提到某个主题想查相关校园消息时使用，例如"找一下关于选课的通知"、"有没有报名类的消息"。',
      parameters: {
        keyword: {
          type: 'string',
          required: true,
          description: '搜索关键词。例如：讲座、选课、报名、放假、招聘、艺术节',
        },
        limit: {
          type: 'number',
          description: '返回条数，默认 10，最大 30。',
        },
      },
      output: {
        schema: { type: 'object' },
        render: (_args, value) => [{ type: 'text', text: value.text }],
      },
      async execute(args, exec) {
        const data = await callApi<{ total: number; items: NoticeItem[] }>(
          '/api/search',
          { q: args.keyword, page_size: Math.min(args.limit ?? 10, 30) },
          exec.signal,
        )
        return {
          text: renderNoticeList(data.items, null, data.total),
          total: data.total,
          keyword: args.keyword,
          notices: data.items.map(n => ({
            id: n.id,
            title: n.title,
            date: n.date,
            url: n.url,
          })),
        }
      },
    }),
  )

  // ── 工具 3：查看单条详情 ──────────────────────────────
  ctx.tools.register(
    defineTool({
      name: 'whu_notice_detail',
      description:
        '查看一条武汉大学校园资讯的完整正文与来源详情。' +
        '当需要对某条已经找到的资讯了解更详细的内容、确认具体要求或核实原文出处时使用。',
      parameters: {
        id: {
          type: 'string',
          required: true,
          description: '资讯的唯一 ID，从 whu_notices 或 whu_search 的结果中获取。',
        },
      },
      output: {
        schema: { type: 'object' },
        render: (_args, value) => [{ type: 'text', text: value.text }],
      },
      async execute(args, exec) {
        const n = await callApi<NoticeDetail>(
          `/api/notices/${encodeURIComponent(args.id)}`,
          {},
          exec.signal,
        )
        const text = [
          `标题：${n.title}`,
          `分类：${n.category_label}　重要度：${LEVEL_LABEL[n.level] ?? n.level}　受众：${AUDIENCE_LABEL[n.audience] ?? n.audience}`,
          `发布日期：${n.date}`,
          `发布机构：${n.publisher || '未标注'}`,
          `作者：${n.author || '未标注'}`,
          `来源栏目：${n.source_name}${n.source_column ? ' · ' + n.source_column : ''}`,
          '',
          '正文：',
          n.content || n.summary || '（无正文内容）',
          '',
          `原文链接：${n.url}`,
          '',
          '提示：以上内容摘自原文，版权归原发布单位所有，重要决策请以原文为准。',
        ].join('\n')

        return { text, id: n.id, title: n.title, url: n.url, content: n.content }
      },
    }),
  )

  // ── 工具 4：资讯来源与统计 ────────────────────────────
  ctx.tools.register(
    defineTool({
      name: 'whu_news_overview',
      description:
        '查看武汉大学校园资讯的整体概览：各分类有多少条、覆盖哪些信息渠道、数据更新到什么时候。' +
        '当用户想了解这个信息源的整体情况、或者问"你们的数据多久更新一次"时使用。',
      parameters: {},
      output: {
        schema: { type: 'object' },
        render: (_args, value) => [{ type: 'text', text: value.text }],
      },
      async execute(_args, exec) {
        const [stats, sources] = await Promise.all([
          callApi<{
            total: number
            date_range: { from: string; to: string } | null
            updated_at: string | null
            by_category: { label: string; count: number }[]
            by_audience: { label: string; count: number }[]
          }>('/api/stats', {}, exec.signal),
          callApi<{
            items: { name: string; item_count: number; latest_date: string }[]
          }>('/api/sources', {}, exec.signal),
        ])

        const catLines = stats.by_category.map(c => `  ${c.label}：${c.count} 条`).join('\n')
        const audLines = stats.by_audience.map(a => `  ${a.label}：${a.count} 条`).join('\n')
        const srcLines = sources.items
          .map(s => `  ${s.name}：${s.item_count} 条（最新 ${s.latest_date}）`)
          .join('\n')

        const text = [
          '武汉大学校园资讯聚合 · 数据概览',
          '',
          `资讯总数：${stats.total} 条`,
          stats.date_range ? `覆盖区间：${stats.date_range.from} 至 ${stats.date_range.to}` : '',
          `数据更新：${stats.updated_at || '未知'}（每日 08:00 与 18:00 自动采集）`,
          '',
          '按分类：',
          catLines,
          '',
          '按受众：',
          audLines,
          '',
          '信息来源渠道：',
          srcLines,
          '',
          '数据来自武汉大学主站与新闻网等官方公开渠道，每条资讯均标注来源与原文链接。',
        ]
          .filter(Boolean)
          .join('\n')

        return { text, total: stats.total, updatedAt: stats.updated_at }
      },
    }),
  )
}
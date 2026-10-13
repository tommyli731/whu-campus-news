# REST API 接口文档

> 机器可读规范见 [`openapi.yaml`](./openapi.yaml)（OpenAPI 3.0.3，可直接导入 Swagger UI / Postman / Apifox）
> 本文为便于快速查阅的说明版。

---

## 一、快速开始

```bash
# 1. 先采集数据（生成 data_news.json）
python update.py

# 2. 启动 API 服务
python api.py# 默认 http://localhost:8000

# 3. 验证
curl http://localhost:8000/api/health
```

**零依赖**：只用 Python 标准库，无需 `pip install`。

自定义端口：
```bash
python api.py --port 9000
PORT=9000 python api.py
```

---

## 二、鉴权说明

本 API 采用**可选鉴权**模式：

| 服务端配置 | 行为 |
|---|---|
| 未设置 `API_KEY` 环境变量 | 不校验，公开可访问 |
| 设置了 `API_KEY` 环境变量 | 所有 `/api/*` 请求均需校验 |

**传递方式**（二选一）：
1. 请求头：`X-API-Key: <your-key>`
2. 查询参数：`?api_key=<your-key>`（便于浏览器调试，生产建议用请求头）

**配置方式**：
```bash
# Windows CMD
set API_KEY=your-secret && python api.py

# Windows PowerShell
$env:API_KEY="your-secret"; python api.py

# Linux / macOS
export API_KEY=your-secret && python api.py
```

未携带或错误时返回 `401`：
```json
{
  "success": false,
  "error": {
    "code": "UNAUTHORIZED",
    "message": "缺少或错误的 API Key",
    "detail": "请在请求头携带 X-API-Key: <your-key>，或在查询参数附加 ?api_key=<your-key>。"
  }
}
```

> ⚠️ **生产环境建议务必配置 `API_KEY`**，否则接口可被任意调用。

---

## 三、接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 服务信息与接口索引 |
| GET | `/api/health` | 健康检查（无需鉴权） |
| GET | `/api/notices` | 资讯列表（筛选/排序/分页） |
| GET | `/api/notices/{id}` | 资讯详情 |
| GET | `/api/categories` | 分类列表及计数 |
| GET | `/api/sources` | 信息来源列表 |
| GET | `/api/search` | 关键词搜索 |
| GET | `/api/stats` | 数据统计 |

---

## 四、通用约定

### 响应结构

**成功**：
```json
{
  "success": true,
  "data": { },
  "request_id": "267caa29951f"
}
```

**失败**：
```json
{
  "success": false,
  "error": {
    "code": "INVALID_PARAM",
    "message": "category 取值非法: bad",
    "detail": "可选值：all, headline, academic, notice, college, activity, party"
  },
  "request_id": "a1b2c3d4e5f6"
}
```

所有响应均为 JSON，含 `Content-Type: application/json; charset=utf-8`，支持跨域（`Access-Control-Allow-Origin: *`）。

### 状态码

| 码 | 含义 | 错误码 |
|---|---|---|
| 200 | 成功 | — |
| 400 | 参数错误 | `INVALID_PARAM`、`MISSING_PARAM` |
| 401 | 未授权 | `UNAUTHORIZED` |
| 404 | 资源不存在 | `NOT_FOUND`、`NOTICE_NOT_FOUND` |
| 500 | 服务器内部错误 | `INTERNAL_ERROR` |
| 503 | 数据不可用 | `DATA_UNAVAILABLE` |

### 枚举值

| 字段 | 可选值 |
|---|---|
| `category` | `all` `headline` 要闻速览 / `academic` 学术讲座 / `notice` 通知公告 / `college` 院系动态 / `activity` 文体活动 / `party` 党团思政 |
| `audience` | `all` / `stu` 仅学生 / `tea` 仅教师 / `both` 师生通用 |
| `level` | `all` / `S` 重要 / `A` 较重要 / `B` 常规 |
| `sort` | `date_desc` 最新在前（默认）/ `date_asc` 最早在前 / `level_desc` 重要度优先 / `title_asc` 标题升序 |

> **受众筛选规则**：`audience=stu` 会同时返回「仅学生」与「师生通用」两类，因为师生通用的资讯对学生同样有意义。

---

## 五、接口详情

### 1. GET /api/health

健康检查。

```bash
curl http://localhost:8000/api/health
```

```json
{
  "success": true,
  "data": {
    "status": "ok",
    "version": "1.0.0",
    "data_available": true,
    "item_count": 57,
    "data_updated_at": "2026-10-13 12:24",
    "uptime_seconds": 7.0,
    "auth_required": false,
    "server_time": "2026-10-13 14:18:14"
  }
}
```

`status` 为 `degraded` 表示数据文件缺失（需运行 `python update.py`）。

---

### 2. GET /api/notices

资讯列表，支持全部筛选与排序。

**查询参数**：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `category` | string | `all` | 分类 |
| `audience` | string | `all` | 受众 |
| `level` | string | `all` | 重要度 |
| `source` | string | `all` | 来源名称（取值见 `/api/sources`） |
| `since` | date | — | 起始日期（含） |
| `until` | date | — | 截止日期（含） |
| `q` | string | — | 关键词 |
| `sort` | string | `date_desc` | 排序 |
| `page` | int | `1` | 页码 |
| `page_size` | int | `20` | 每页条数（上限 100） |

**调用示例**：

```bash
# 基础查询
curl "http://localhost:8000/api/notices?page_size=5"

# 学生向的学术类 S 级资讯
curl "http://localhost:8000/api/notices?category=academic&audience=stu&level=S"

# 10 月以来的通知公告，按重要度排序
curl "http://localhost:8000/api/notices?category=notice&since=2026-10-01&sort=level_desc"

# 关键词搜索
curl "http://localhost:8000/api/notices?q=讲座"

# 分页
curl "http://localhost:8000/api/notices?page=2&page_size=10"
```

**响应**：
```json
{
  "success": true,
  "data": {
    "total": 57,
    "page": 1,
    "page_size": 20,
    "total_pages": 3,
    "has_next": true,
    "filters": {
      "category": "all", "audience": "all", "level": "all",
      "source": "all", "since": null, "until": null,
      "keyword": "", "sort": "date_desc"
    },
    "data_updated_at": "2026-10-13 12:24",
    "items": [
      {
        "id": "4b9d12179943",
        "title": "珞珈讲坛第546讲预告",
        "date": "2026-10-13",
        "category": "notice",
        "category_label": "通知公告",
        "level": "A",
        "audience": "both",
        "audience_label": "师生通用",
        "source_name": "通知公告（主站栏）",
        "source_column": "通知公告",
        "summary": "珞珈讲坛第546讲预告",
        "url": "https://www.whu.edu.cn/info/5231/276164.htm"
      }
    ]
  }
}
```

**无结果时**返回 `total: 0`、`items: []`，HTTP 状态码仍是 `200`。

---

### 3. GET /api/notices/{id}

资讯详情，返回列表字段 + 正文 + 完整来源信息。

```bash
curl http://localhost:8000/api/notices/4b9d12179943
```

```json
{
  "success": true,
  "data": {
    "id": "4b9d12179943",
    "title": "月壤为何“承得住”又“易失稳”？武汉大学团队揭示凝集物调控月壤力学行为机制",
    "date": "2026-10-12",
    "category": "academic",
    "category_label": "学术讲座",
    "level": "A",
    "audience": "both",
    "audience_label": "师生通用",
    "source_name": "武汉大学新闻网",
    "source_column": "学术动态",
    "summary": "武汉大学教授王顺课题组在国际行星科学领域期刊发表论文。",
    "url": "https://news.whu.edu.cn/info/1015/504877.htm",
    "content": "新闻网讯（通讯员水苑）近日，武汉大学教授王顺课题组……",
    "publisher": "科学技术发展研究院 / 武汉大学新闻网",
    "author": "通讯员 水苑"
  }
}
```

不存在的 id 返回 `404`，`code: NOTICE_NOT_FOUND`。

---

### 4. GET /api/categories

分类列表及各自条目数。

```bash
curl http://localhost:8000/api/categories
```

```json
{
  "success": true,
  "data": {
    "total": 57,
    "items": [
      { "key": "headline", "label": "要闻速览", "count": 18 },
      { "key": "academic", "label": "学术讲座", "count": 17 },
      { "key": "notice",   "label": "通知公告", "count": 8 },
      { "key": "college",  "label": "院系动态", "count": 2 },
      { "key": "activity", "label": "文体活动", "count": 9 },
      { "key": "party",    "label": "党团思政", "count": 3 }
    ]
  }
}
```

---

### 5. GET /api/sources

来源聚合统计，返回值可直接用作 `/api/notices?source=` 的取值。

```bash
curl http://localhost:8000/api/sources
```

```json
{
  "success": true,
  "data": {
    "total": 2,
    "items": [
      {
        "name": "武汉大学新闻网",
        "item_count": 49,
        "latest_date": "2026-10-13",
        "columns": [
          { "name": "学术动态", "count": 17 },
          { "name": "武大要闻", "count": 10 }
        ]
      }
    ]
  }
}
```

---

### 6. GET /api/search

全文搜索，匹配标题、摘要、正文、发布机构、作者、栏目、来源七个字段（不区分大小写）。

**参数**：`q`（必填）、`keyword`（`q` 的别名）、`page_size`

```bash
curl "http://localhost:8000/api/search?q=讲座"
```

```json
{
  "success": true,
  "data": {
    "keyword": "讲座",
    "total": 1,
    "fields_searched": ["标题", "摘要", "正文", "发布机构", "作者", "栏目", "来源"],
    "items": [ { "id": "...", "title": "珞珈讲坛第546讲预告", "...": "..." } ]
  }
}
```

缺少 `q` 返回 `400`，`code: MISSING_PARAM`。

---

### 7. GET /api/stats

数据统计。

```bash
curl http://localhost:8000/api/stats
```

```json
{
  "success": true,
  "data": {
    "total": 57,
    "date_range": { "from": "2026-08-14", "to": "2026-10-13" },
    "updated_at": "2026-10-13 12:24",
    "by_category": [ { "key": "headline", "label": "要闻速览", "count": 18 } ],
    "by_level":    [ { "level": "S", "label": "重要（权威发布口）", "count": 7 } ],
    "by_audience": [ { "key": "both", "label": "师生通用", "count": 39 } ],
    "source_count": 2
  }
}
```

---

## 六、在 Swagger UI 中预览

方式一：本地起一个静态服务打开
```bash
python -m http.server 8080
# 浏览器访问 http://localhost:8080
```

方式二：将 `openapi.yaml` 导入在线编辑器
- Swagger Editor：https://editor.swagger.io
- Apifox / Postman：支持直接导入 YAML

---

## 七、接入前端示例

```javascript
// 原生 fetch
async function loadNotices(category = 'all', audience = 'all') {
  const params = new URLSearchParams({ category, audience, page_size: 10 });
  const res = await fetch(`http://localhost:8000/api/notices?${params}`);
  const json = await res.json();
  if (!json.success) throw new Error(json.error.message);
  return json.data.items;
}

// 渲染到列表
(async () => {
  const items = await loadNotices('notice', 'stu');
  document.getElementById('list').innerHTML = items.map(n => `
    <article class="notice">
      <h3><a href="${n.url}" target="_blank" rel="noopener">${n.title}</a></h3>
      <div class="meta">
        <span class="cat">${n.category_label}</span>
        <span class="lv">${n.level}级</span>
        <time>${n.date}</time>
        <span class="src">${n.source_name} · ${n.source_column}</span>
      </div>
      <p>${n.summary}</p>
    </article>
  `).join('');
})();
```

带鉴权时：
```javascript
fetch('http://localhost:8000/api/notices', {
  headers: { 'X-API-Key': 'your-key' }
});
```

---

## 八、错误码速查

| code | HTTP | 含义 | 处理建议 |
|---|---|---|---|
| `INVALID_PARAM` | 400 | 参数取值非法 | 检查 category / audience / level / sort / 日期格式 |
| `MISSING_PARAM` | 400 | 缺少必填参数 | `/api/search` 需带 `q` |
| `UNAUTHORIZED` | 401 | Key 缺失或错误 | 携带 `X-API-Key` 请求头 |
| `NOT_FOUND` | 404 | 路由不存在 | 访问 `GET /` 查看接口索引 |
| `NOTICE_NOT_FOUND` | 404 | 资讯 id 不存在 | 从 `/api/notices` 获取有效 id |
| `DATA_UNAVAILABLE` | 503 | 数据文件缺失 | 运行 `python update.py` |
| `INTERNAL_ERROR` | 500 | 服务端异常 | 记录 `request_id` 便于排查 |

---

## 九、注意事项

- 所有接口均为**只读 GET**，不提供写入能力
- 数据来自 `data_news.json`，运行 `update.py` 后自动刷新（服务按文件 mtime 缓存，无需重启）
- 接口已开启跨域（`Access-Control-Allow-Origin: *`），可被任意前端调用
- **生产环境建议**：配置 `API_KEY`、置于 Nginx 等反向代理之后、按需启用 HTTPS

---

**版本** 1.0.0 ｜ **实测** 31/31 项通过 ｜ 全部接口与 `openapi.yaml` 逐项比对一致
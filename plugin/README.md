# DeepSeek Harness 校园资讯插件

让 DeepSeek Harness 的 AI 助手直接查询武汉大学校园通知、讲座与活动。

装上之后，直接跟 AI 说话就行：

> **你**：帮我看看最近有什么重要的通知
>
> **AI**：（自动调用插件）找到 3 条重要通知，其中「珞珈讲坛第546 讲预告」今天刚发布…

---

## 提供的工具

| 工具 | 用途 | 参数 |
|---|---|---|
| `whu_notices` | 浏览校园资讯 | `category` 分类 / `audience` 受众 / `level` 重要度 / `days` 最近天数 / `limit` 条数 |
| `whu_search` | 关键词全文搜索 | `keyword` 关键词（必填）/ `limit` |
| `whu_notice_detail` | 查看单条完整正文 | `id` 资讯 ID（必填） |
| `whu_news_overview` | 资讯概览与数据统计 | 无 |

### 分类取值

| 参数值 | 含义 |
|---|---|
| `notice` | 通知公告 |
| `academic` | 学术讲座 |
| `headline` | 要闻速览 |
| `college` | 院系动态 |
| `activity` | 文体活动 |
| `party` | 党团思政 |

### 其他筛选

- **受众**：`stu`（与学生相关）/ `tea`（与教师相关）/ `both`（仅师生通用）
- **重要度**：`S`（重要）/ `A`（较重要）/ `B`（常规）
- **最近天数**：如 `days: 7` 表示最近一周

---

## 安装

### 方式一：从仓库复制（推荐）

```bash
# 1. 克隆本仓库
git clone https://github.com/tommyli731/whu-campus-news.git

# 2. 复制插件到 Harness 插件目录
cp -r whu-campus-news/plugin ~/.deepseek-harness/plugins/

# 3. 重启 Harness
```

### 方式二：在 Creator mode 中安装

启动 Harness 后在对话里说：

> 加载 plugin 目录下的 dsh-plugin-whu-news 插件

### 方式三：本地开发

```bash
cd whu-campus-news/plugin
```

修改 `src/index.ts` 中的 `API_BASE` 指向你自己的服务，或设置环境变量：

```bash
export WHU_NEWS_API="http://localhost:8000"
```

---

## 数据来源

插件调用公开 API：

```
https://whu-campus-news.app.workbuddy.host
```

| 接口 | 用途 |
|---|---|
| `/api/notices` | 资讯列表（筛选/排序/分页） |
| `/api/search` | 关键词搜索 |
| `/api/notices/{id}` | 资讯详情 |
| `/api/stats` | 统计 |
| `/api/sources` | 来源统计 |
| `/api/health` | 健康检查 |

- **无需注册、无需 API Key**
- **每日 08:00 与 18:00（北京时间）自动采集更新**
- 数据来源为武汉大学主站、新闻网等官方公开渠道
- 每条资讯均标注来源机构、栏目与原文链接

---

## 自行部署 API

如果不想用公共实例，可自行部署（零第三方依赖，只需 Python 3.7+）：

```bash
cd whu-campus-news

# 采集数据
python update.py

# 启动服务
python api.py# 默认 http://localhost:8000

# 指向自己的服务
export WHU_NEWS_API="http://localhost:8000"
```

可选鉴权：

```bash
export API_KEY=your-secret && python api.py
```

---

## 项目结构

```
plugin/
├── package.json          Cordis 插件清单
├── plugin.json           插件元信息与工具列表
├── src/
│   └── index.ts插件入口（注册 4 个工具）
├── test-core.mjs         核心逻辑测试（无需 DSH 环境）
└── README.md             本文件
```

---

## 开发与测试

核心逻辑可脱离 Harness 独立测试：

```bash
node test-core.mjs
```

输出示例：

```
【工具1】whu_notices — 浏览校园资讯
  ✅ 调用成功，57 条可用，返回 10 条

--- 模型看到的文本输出 ---
共找到 57 条资讯，显示前 10 条。

1. 【通知公告】珞珈讲坛第546讲预告
   日期：2026-10-13　重要度：较重要　受众：师生通用
   来源：通知公告（主站栏） · 通知公告
   摘要：珞珈讲坛第546讲预告
   原文：https://www.whu.edu.cn/info/5231/276164.htm
```

---

## 实现要点

按 DeepSeek Harness 官方 `adding-a-tool.md` 规范编写：

- 入口 `export function apply(ctx: Context)`，声明 `inject = ['tools']`
- 用 `defineTool` 注册工具，参数 schema 为 `ParameterSchemaSpec`（`{ type, required, description }`）
- `output.render` 返回模型可读的文本内容
- `execute(args, exec)` 中 `args` 由 schema 自动推断类型，`exec.signal` 用于取消
- `AbortSignal.any()` 组合取消信号与超时

---

## 已知限制

- 搜索为全文匹配，搜"讲座"可能命中摘要中提及"讲座"的文章（如含"讲座"字样的培训通知），而非严格的讲座预告
- 部分主站通知公告的正文较短（采集自列表页摘要），可调用 `whu_notice_detail` 后引导用户查看原文
- 微信公众号渠道尚未接入

---

## 许可

MIT

资讯内容版权归原发布单位所有，本插件仅作索引与检索。
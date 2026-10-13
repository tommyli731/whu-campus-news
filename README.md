# 武汉大学校园资讯聚合

汇总武汉大学各官方渠道（主站、新闻网）发布的校园资讯，按**学生**与**教师**两个视角分开呈现。

> ⚠️ 本项目为**非官方第三方工具**，与武汉大学及任何院系、职能部门无隶属或授权关系。
> 所有资讯版权归原发布单位所有，本站仅作原文摘录与索引。

---

## 功能特性

- **双视角分离**：学生资讯与教师资讯明确区分，互不混杂
- **6 大分类**：要闻速览、学术讲座、通知公告、院系动态、文体活动、党团思政
- **三档重要度**：S 级（权威发布口）/ A 级（较重要）/ B 级（常规）
- **自动采集**：7 个官方信源，定时抓取公开页面
- **来源可追溯**：每条资讯标注栏目、发布机构、作者、原文链接
- **49 个渠道清单**：含类型、所属单位、内容范围与访问入口
- **REST API**：8 个接口，附OpenAPI 3.0 规范
- **AI 插件**：DeepSeek Harness 插件，4 个模型可调用工具
- **自动更新**：GitHub Actions 每日两次采集
- **零依赖**：仅使用 Python 标准库，无需 `pip install`

---

## 快速开始

```bash
# 1. 采集数据
python update.py

# 2. 启动网站（双击 index.html 也可直接打开）
#    或启动 API 服务
python api.py     # http://localhost:8000
```

要求：Python 3.7+，无需任何第三方库。

### 线上地址（无需部署，直接可访问）

| 类型 | 地址 |
|---|---|
| 🟢 **API** | `https://whu-campus-news.app.workbuddy.host/api/notices` |
| 🟢 **网站** | `https://whu-campus-news.app.workbuddy.host/` |

任何人可直接调用，无需注册与 API Key。数据每日 08:00与 18:00 自动采集。

---

## 🤖 DeepSeek Harness 插件

让 AI 助手直接查询校园资讯，装上后对AI 说话即可：

> **你**：最近有什么重要的通知？
> **AI**：（自动调用插件）找到 3 条重要通知……

插件位于 [`plugin/`](./plugin) 目录，随本仓库一起分发：

```bash
git clone https://github.com/tommyli731/whu-campus-news.git
cp -r whu-campus-news/plugin ~/.deepseek-harness/plugins/
```

提供 4 个工具：`whu_notices` 浏览资讯 · `whu_search` 关键词搜索 · `whu_notice_detail` 查看详情 · `whu_news_overview` 数据概览

详见 [plugin/README.md](./plugin/README.md)。

---

## 项目结构

```
├── index.html              # 主网站（响应式，支持移动端）
├── data_news.json          # 采集生成的资讯数据
├── api.py                  # REST API 服务
├── openapi.yaml            # OpenAPI 3.0 规范
├── API文档.md              # 接口文档（可读版）
├── update.py               # 一键更新数据
├── release.py              # 版本化发布工具
├── crawler/
│   └── crawler.py          # 采集脚本（零依赖）
├── plugin/                 # DeepSeek Harness 插件
│   ├── package.json
│   ├── plugin.json
│   ├── src/index.ts        # 插件入口（4 个工具）
│   └── test-core.mjs       # 插件逻辑测试
├── .github/workflows/
│   └── crawler.yml         # 定时自动采集
├── snapshots/              # 版本快照存档
├── 渠道清单与信息架构规划.md
├── 数据采集说明.md
└── 版本存档记录.md
```

---

## 常用命令

```bash
# 采集最近 60 天数据
python update.py --days 60

# 只采集指定信源
python crawler/crawler.py --source news_academic

# 启动 API（自定义端口）
python api.py --port 9000

# 启用鉴权
export API_KEY=your-secret && python api.py

# 版本化发布（建快照 + 追加记录）
python release.py --ver 1.5 --desc "说明文字" --data
```

---

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/notices` | 资讯列表（筛选/排序/分页） |
| GET | `/api/notices/{id}` | 资讯详情 |
| GET | `/api/categories` | 分类及计数 |
| GET | `/api/sources` | 来源列表 |
| GET | `/api/search` | 关键词搜索 |
| GET | `/api/stats` | 数据统计 |

```bash
curl "http://localhost:8000/api/notices?category=notice&sort=level_desc"
curl "http://localhost:8000/api/search?q=讲座"
```

完整文档见 [`API文档.md`](./API文档.md) 与 [`openapi.yaml`](./openapi.yaml)。

---

## 数据来源

| 信源 | 栏目 |
|---|---|
| 武汉大学新闻网 | 武大要闻、综合新闻、学术动态、珞珈人物、缤纷校园、媒体武大 |
| 武汉大学主站 | 通知公告 |

全部为公开页面，仅采集标题、日期、摘要、来源信息与原文链接。

---

## 定时更新

建议每天执行两次（早 8 点 / 晚 6 点）：

**Linux / macOS（cron）**
```bash
crontab -e
0 8,18 * * * cd /path/to/project && python3 update.py >> logs/update.log 2>&1
```

**Windows（任务计划程序）**
```
程序: python
参数: <项目路径>\update.py
触发: 每天 08:00 和 18:00
```

---

## 注意

- 仅采集公开页面，不涉及任何登录态或私有接口
- 数据为采集时的快照，涉及选课、放假、缴费等重要决策请以原文为准
- 请勿将回溯天数调得过大（建议 ≤ 90 天），避免给服务器造成压力
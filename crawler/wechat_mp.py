#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号采集适配器（支持三种后端，自动探测）

与主爬虫的区别：
- 主爬虫 crawler.py抓学校官网（VSB9 静态页，零依赖）
- 本模块 wechat_mp.py   抓微信公众号（纯标准库，零依赖）

支持的后端（按 MP_BACKEND 指定，或自动依次探测）：

  1. wechat2rss —— 公共服务 wechat2rss.xlab.app
     · 无需任何登录
     · 但仅收录约 800 个技术/安全类公众号，且不可自行添加
     · 适合：技术类公众号；不适合武大（未收录）
     RSS 格式：https://wechat2rss.xlab.app/feed/{hash}.xml
     列表：https://raw.githubusercontent.com/ttttmr/Wechat2RSS/master/list/all.md

  2. werss —— 自建 WeRSS（github.com/rachelos/we-mp-rss）
     · 支持任意公众号
     · 需部署 + 微信扫码授权
     · 需 Docker 与 Chromium
     RSS 格式：{WERSS_BASE}/feeds/all.rss

  3. weread —— 微信读书反向订阅
     · 无需微信扫码，只需注册微信读书账号
     · 支持任意公众号（微信读书可关注公众号）
     · 需部署 wewe-rss（注意：原 cooderl/wewe-rss 已归档，2026-01-19 起不再维护）
     RSS 格式：{WEREAD_BASE}/feeds/all.rss

环境变量：
  MP_BACKEND      = auto | wechat2rss | werss | weread   （默认 auto）
  WERSS_BASE      = http://localhost:8001
  WEREAD_BASE     = http://localhost:4000
  MP_RSS_URL      = 直接指定某个 RSS 地址（最高优先级，跳过后端探测）
  MP_FEED_URLS    = 多个 RSS 地址，逗号分隔
  WERSS_TOKEN     = WeRSS API Token（可选）
"""

import os
import re
import json
import hashlib
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
from xml.etree import ElementTree

# ── 后端配置 ──────────────────────────────────────────────
MP_BACKEND = os.environ.get('MP_BACKEND', 'auto').strip().lower()
MP_RSS_URL = os.environ.get('MP_RSS_URL', '').strip()
MP_FEED_URLS = [u.strip() for u in os.environ.get('MP_FEED_URLS', '').split(',') if u.strip()]

WERSS_BASE = os.environ.get('WERSS_BASE', 'http://localhost:8001').rstrip('/')
WEREAD_BASE = os.environ.get('WEREAD_BASE', 'http://localhost:4000').rstrip('/')
WERSS_TOKEN = os.environ.get('WERSS_TOKEN', '').strip()

W2R_BASE = 'https://wechat2rss.xlab.app'
W2R_LIST_MIRRORS = [
    'https://ghproxy.net/https://raw.githubusercontent.com/ttttmr/Wechat2RSS/master/list/all.md',
    'https://raw.githubusercontent.com/ttttmr/Wechat2RSS/master/list/all.md',
]

TIMEOUT = 20

# 公众号分类映射：按订阅号名称识别归入哪个栏目
MP_CATEGORY_RULES = [
    (['珞珈讲坛', '讲堂', '讲座'], 'academic', '珞珈讲坛'),
    (['党委', '党建', '思政', '红色', '青年'], 'party', '党团思政'),
    (['团委', '学工', '学生工作', '研究生院', '学生处'], 'activity', '学生工作'),
    (['招生', '就业', '创新创业', '培养'], 'headline', '招生就业'),
    (['人事', '教师', '工会', '离退'], 'headline', '人事教工'),
    (['教务', '教学', '本科教学', '研究生教学'], 'notice', '教务通知'),
    (['后勤', '保卫', '资产', '图书馆', '校医院'], 'notice', '后勤服务'),
    (['体育', '艺术', '文艺', '音乐', '美术'], 'activity', '文体活动'),
    (['科学', '科研', '技术', '实验室'], 'academic', '科研动态'),
    (['国际', '交流', '合作'], 'headline', '国际交流'),
]
DEFAULT_CATEGORY = ('headline', '微信公众号')

LV_RULES = {
    'S': ['公示', '录取', '推免', '截止', '紧急', '重要', '必须', '报名', '招聘', '公示期', '揭牌', '任命'],
    'A': ['获奖', '入选', '当选', '冠军', '冠军', '举办', '开幕', '启动', '交流', '访问', '特级', '晋升'],
}

AUD_TEACHER = ['教师', '教职工', '教授', '院士', '团队', '科研', '论文', '成果', '招聘', '职称',
               '人才', '党建', '支部', '党员', '博士', '导师', '学科']
AUD_STUDENT = ['学生', '本科生', '研究生', '新生', '开学', '课', '考试', '选课', '奖学金',
               '助学金', '艺术节', '运动会', '社团', '志愿', '班级', '学子', '毕业', '就业',
               '实习', '宿舍', '青春', '招新']


def _headers():
    h = {'User-Agent': 'WHU-Campus-News-WeChat/1.0', 'Accept': '*/*'}
    if WERSS_TOKEN:
        h['Authorization'] = f'Bearer {WERSS_TOKEN}'
    return h


def fetch(url):
    """发起GET 请求，返回文本；失败返回 None。"""
    try:
        req = urllib.request.Request(url, headers=_headers())
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode('utf-8', 'ignore')
    except Exception:
        return None


def parse_date(s):
    """把 RSS 的 pubDate 转成 YYYY-MM-DD。"""
    if not s:
        return ''
    # RFC 822: Tue, 14 Oct 2026 10:00:00 +0800
    m = re.match(r'[A-Za-z]{3},\s+(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', s.strip())
    if m:
        months = {'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05', 'Jun': '06',
                  'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'}
        return f'{m.group(3)}-{months.get(m.group(2), "01")}-{int(m.group(1)):02d}'
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        return m.group(0)
    return ''


def strip_html(html):
    """把 HTML 摘要转纯文本。"""
    if not html:
        return ''
    t = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.S | re.I)
    t = re.sub(r'<br\s*/?>|</p>', '\n', t, flags=re.I)
    t = re.sub(r'<[^>]+>', '', t)
    t = t.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    t = re.sub(r'\n{2,}', '\n', t)
    return re.sub(r'[ \t]{2,}', ' ', t).strip()


def classify(mp_name, title, desc):
    """按订阅号名与标题判断分类、级别、受众。"""
    cat, col = None, None
    for kws, c, cn in MP_CATEGORY_RULES:
        if any(k in mp_name for k in kws):
            cat, col = c, cn
            break
    if cat is None:
        # 退而看标题
        for kws, c, cn in MP_CATEGORY_RULES:
            if any(k in title for k in kws):
                cat, col = c, cn
                break
    if cat is None:
        cat, col = DEFAULT_CATEGORY

    t = title + ' ' + desc
    lv = 'S' if any(k in t for k in LV_RULES['S']) else (
        'A' if any(k in t for k in LV_RULES['A']) else 'B')

    ts = any(k in t for k in AUD_TEACHER)
    ss = any(k in t for k in AUD_STUDENT)
    if cat == 'notice':
        aud = 'both'
    elif cat == 'activity':
        aud = 'stu'
    elif ts and not ss:
        aud = 'tea'
    elif ss and not ts:
        aud = 'stu'
    else:
        aud = 'both'
    return cat, lv, aud, col


def check_werss():
    """探测 WeRSS 是否可用。返回 (可用?, 说明)。"""
    return _probe_rss(f'{WERSS_BASE}/feeds/all.rss', 'WeRSS')


def check_weread():
    """探测微信读书 RSS 服务。返回 (可用?, 说明)。"""
    return _probe_rss(f'{WEREAD_BASE}/feeds/all.rss', '微信读书')


def _probe_rss(url, label):
    txt = fetch(url)
    if not txt:
        return False, None
    try:
        root = ElementTree.fromstring(txt)
        items = list(root.iter('item'))
        return True, f'可用，{len(items)} 篇'
    except Exception:
        return False, None


def load_w2r_index():
    """拉取 Wechat2RSS 的公众号收录索引（多镜像容错）。"""
    txt = None
    for u in W2R_LIST_MIRRORS:
        txt = fetch(u)
        if txt:
            break
    if not txt:
        return {}
    out = {}
    for m in re.finditer(r'\[([^\]]+)\]\(' + re.escape(W2R_BASE) + r'/feed/([0-9a-f]+)\.xml\)', txt):
        out[m.group(1)] = f'{W2R_BASE}/feed/{m.group(2)}.xml'
    return out


def detect_backend():
    """探测可用的后端。返回 (后端名, RSS地址列表, 说明)。"""
    # 1) 用户直接指定
    if MP_RSS_URL:
        return 'direct', [MP_RSS_URL], '使用 MP_RSS_URL'
    if MP_FEED_URLS:
        return 'direct', MP_FEED_URLS, f'使用 MP_FEED_URLS（{len(MP_FEED_URLS)} 个源）'

    order = ['wechat2rss', 'weread', 'werss'] if MP_BACKEND == 'auto' else [MP_BACKEND]

    for be in order:
        if be == 'wechat2rss':
            ok, info = _probe_rss(f'{W2R_BASE}/feed/5b925323244e9737c39285596c53e3a2f4a30774.xml',
                                  'Wechat2RSS')
            if ok:
                idx = load_w2r_index()
                return 'wechat2rss', [], f'公共服务可用，已收录 {len(idx)} 个公众号'
        elif be == 'weread':
            ok, info = check_weread()
            if ok:
                return 'weread', [f'{WEREAD_BASE}/feeds/all.rss'], f'微信读书服务：{info}'
        elif be == 'werss':
            ok, info = check_werss()
            if ok:
                return 'werss', [f'{WERSS_BASE}/feeds/all.rss'], f'WeRSS：{info}'
    return None, [], '无可用后端'


def fetch_rss_items(urls, backend):
    """从一组 RSS 地址拉取并解析条目。"""
    items = []
    for url in urls:
        txt = fetch(url)
        if not txt:
            continue
        try:
            root = ElementTree.fromstring(txt)
        except Exception:
            continue
        channel_title = (root.findtext('.//channel/title') or '').strip()
        for it in root.iter('item'):
            title = (it.findtext('title') or '').strip()
            link = (it.findtext('link') or '').strip()
            pub = parse_date(it.findtext('pubDate') or '')
            desc = strip_html(it.findtext('description') or '')
            mp = (it.findtext('{http://purl.org/dc/elements/1.1/}creator') or '').strip()
            if not mp:
                mp = re.sub(r'\s*-\s*(WeRSS|Wechat2RSS).*$', '', channel_title).strip()
            if title and link:
                items.append({'title': title, 'link': link, 'date': pub,
                              'desc': desc, 'mp': mp or '微信公众号'})
    return items


# 关注的公众号（按名称关键词匹配 wechat2rss 收录索引）
# 说明：wechat2rss 免费服务只能取其已收录的公众号，无法自行添加。
# 若某公众号不在其列表中，会在运行时提示"未收录"。
WATCH_KEYWORDS = [
    '武汉大学', '武大', '珞珈', '武大新闻网', '武大研究生',
    '武大教务', '武大团委', '武大招聘', '武大图书馆',
]


def collect(since):
    """采集公众号文章，返回统一格式的条目列表。"""
    backend, urls, info = detect_backend()
    if backend is None:
        print('    [公众号] 未探测到可用后端，跳过')
        print(f'    [公众号] 提示：可用 MP_RSS_URL 环境变量直接指定 RSS 地址')
        return []

    print(f'    [公众号] 后端={backend}（{info}）')

    if backend == 'wechat2rss':
        idx = load_w2r_index()
        if not idx:
            print('    [公众号] 收录索引拉取失败')
            return []
        urls = []
        hit = []
        for kw in WATCH_KEYWORDS:
            for name, u in idx.items():
                if kw in name and u not in urls:
                    urls.append(u)
                    hit.append(name)
        if not urls:
            print(f'    [公众号] wechat2rss 未收录目标公众号（共收录 {len(idx)} 个）')
            print('    [公众号] 该免费服务只收录技术/安全类公众号，武大不在其中')
            print('    [公众号] 若需任意公众号，请改用 WeRSS 或微信读书方案')
            return []
        print(f'    [公众号] 命中 {len(hit)} 个：{"、".join(hit[:5])}{"..." if len(hit) > 5 else ""}')

    raw = fetch_rss_items(urls, backend)
    if not raw:
        print('    [公众号] 未获取到文章')
        return []

    out = []
    for r in raw:
        d = r['date']
        if not d or d < since:
            continue
        cat, lv, aud, col = classify(r['mp'], r['title'], r['desc'])
        out.append(dict(
            id='W' + hashlib.md5(r['link'].encode()).hexdigest()[:11],
            t=r['title'], d=d, c=cat, lv=lv, aud=aud,
            org=f"{r['mp']}（微信公众号）", by=r['mp'],
            col=col, ch='微信公众号', url=r['link'],
            s=(r['desc'] or r['title'])[:120],
            b=r['desc'] or r['title'],
            _from='wechat',
        ))
    print(f'    [公众号] 解析 {len(raw)} 篇，新增 {len(out)} 条')
    return out


# 供主爬虫调用
SOURCE_NAME = '微信公众号（经 WeRSS）'


if __name__ == '__main__':
    sys = __import__('sys')
    days = 60
    if '--days' in sys.argv:
        days = int(sys.argv[sys.argv.index('--days') + 1])
    since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    print('=' * 54)
    print('微信公众号采集适配器')
    print('=' * 54)
    print(f'指定后端：{MP_BACKEND}')
    print(f'回溯天数：{days}（自 {since} 起）')
    print()

    backend, urls, info = detect_backend()
    if backend is None:
        print('后端探测：❌ 未发现可用后端')
        print()
        print('可选方案：')
        print('  1. 直接指定 RSS 地址（最简单）：')
        print('     set MP_RSS_URL=https://example.com/feed.xml')
        print('  2. 部署 WeRSS（支持任意公众号，需扫码）：')
        print('     set MP_BACKEND=werss && set WERSS_BASE=http://localhost:8001')
        print('  3. 部署微信读书反向订阅（支持任意公众号，无需微信扫码）：')
        print('     set MP_BACKEND=weread && set WEREAD_BASE=http://localhost:4000')
        sys.exit(1)

    print(f'后端探测：✅ {backend} —— {info}')
    print()
    items = collect(since)
    print()
    if items:
        print(f'共{len(items)} 条：')
        for i in items[:8]:
            print(f"  [{i['d']}] [{i['c']}/{i['lv']}级/{i['aud']}] {i['t'][:40]}")
    else:
        print('未采集到文章。')
    print('=' * 54)
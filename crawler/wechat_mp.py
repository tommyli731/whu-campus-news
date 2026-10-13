#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号采集适配器（依赖 WeRSS）

与主爬虫的区别：
-主爬虫 crawler.py     抓学校官网（VSB9 静态页，零依赖）
- 本模块wechat_mp.py   抓微信公众号（通过 WeRSS 转 RSS，零依赖）

前置条件：
1. 已部署 WeRSS 并完成扫码授权（见数据采集说明.md）
2. WeRSS 服务地址，默认 http://localhost:8001
   可用环境变量 WERSS_BASE 覆盖
3. WeRSS API Token（可选），可用环境变量 WERSS_TOKEN 提供

若WeRSS 未部署，本模块会静默返回空列表，不影响主爬虫正常工作。
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

# WeRSS 服务地址与凭据
WERSS_BASE = os.environ.get('WERSS_BASE', 'http://localhost:8001').rstrip('/')
WERSS_TOKEN = os.environ.get('WERSS_TOKEN', '').strip()
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
    """探测 WeRSS 是否可用。返回 (可用?, 版本信息)。"""
    url = f'{WERSS_BASE}/api/feeds'
    txt = fetch(url)
    if txt is None:
        return False, None
    try:
        data = json.loads(txt)
        n = len(data.get('data', []) or data.get('feeds', []) or [])
        return True, f'可用，订阅源 {n} 个'
    except Exception:
        return False, None


def fetch_feed_items():
    """拉取 WeRSS 聚合 RSS（all.rss）。返回解析后的条目列表。"""
    url = f'{WERSS_BASE}/feeds/all.rss'
    txt = fetch(url)
    if not txt:
        return []
    try:
        root = ElementTree.fromstring(txt)
    except Exception:
        return []

    items = []
    for it in root.iter('item'):
        title = (it.findtext('title') or '').strip()
        link = (it.findtext('link') or '').strip()
        pub = parse_date(it.findtext('pubDate') or '')
        desc = strip_html(it.findtext('description') or '')
        # 公众号名通常在 feed title 或 author
        mp = (it.findtext('{http://purl.org/dc/elements/1.1/}creator') or '').strip()
        if not mp:
            feed_title = (root.findtext('.//channel/title') or '').strip()
            mp = feed_title.replace('- WeRSS', '').replace('-', '').strip()

        if not title or not link:
            continue
        items.append({'title': title, 'link': link, 'date': pub,
                      'desc': desc, 'mp': mp or '微信公众号'})
    return items


def collect(since):
    """采集公众号文章，返回统一格式的条目列表。"""
    ok, info = check_werss()
    if not ok:
        print(f'    [公众号] WeRSS 不可达({WERSS_BASE})，跳过')
        return []

    raw = fetch_feed_items()
    if not raw:
        print('    [公众号] 未获取到文章（可能还未订阅任何公众号）')
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
    days = 60
    if '--days' in __import__('sys').argv:
        days = int(__import__('sys').argv[__import__('sys').argv.index('--days') + 1])
    since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    print(f'采集公众号文章，回溯至 {since}')
    ok, info = check_werss()
    print(f'WeRSS 状态：{"✅" if ok else "❌"} {info or f"不可达（{WERSS_BASE}）"}')
    if ok:
        items = collect(since)
        print(f'\n共{len(items)} 条')
        for i in items[:5]:
            print(f"  [{i['d']}] [{i['c']}/{i['lv']}级/{i['aud']}] {i['t'][:40]}")
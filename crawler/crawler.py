#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
武汉大学校园资讯聚合 - 采集脚本
仅使用 Python 标准库，无需安装第三方依赖，可部署到任意环境。

用法：
  python crawler.py            # 采集并生成 data/news.json
  python crawler.py --days 30  # 采集最近 30 天
  python crawler.py --source主站  # 仅采集指定信源
"""

import json, re, os, sys, time, argparse, hashlib
import urllib.request, urllib.error
import urllib.parse
from datetime import datetime, timedelta
from html.parser import HTMLParser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(BASE_DIR, 'data', 'news.json')
STATE_FILE = os.path.join(BASE_DIR, 'data', 'state.json')

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
TIMEOUT = 25

# ---------------- 采集源配置 ----------------
SOURCES = [
    dict(key='news_headline', ch='武汉大学新闻网', col='武大要闻', cat='headline',
         url='https://news.whu.edu.cn/wdzx/wdyw.htm', mode='vlist'),
    dict(key='news_comprehensive', ch='武汉大学新闻网', col='综合新闻', cat='headline',
         url='https://news.whu.edu.cn/wdzx/zhxw.htm', mode='vlist'),
    dict(key='news_academic', ch='武汉大学新闻网', col='学术动态', cat='academic',
         url='https://news.whu.edu.cn/kydt.htm', mode='vlist'),
    dict(key='news_person', ch='武汉大学新闻网', col='珞珈人物', cat='college',
         url='https://news.whu.edu.cn/ljrw.htm', mode='vlist'),
    dict(key='news_campus',  ch='武汉大学新闻网', col='缤纷校园', cat='activity',
         url='https://news.whu.edu.cn/xywh/bfxy.htm', mode='vlist'),
    dict(key='news_media',   ch='武汉大学新闻网', col='媒体武大', cat='headline',
         url='https://news.whu.edu.cn/mtwd.htm', mode='vlist'),
    dict(key='main_notice',  ch='通知公告（主站栏）', col='通知公告', cat='notice',
         url='https://www.whu.edu.cn/tzgg.htm', mode='table'),
]

# 分类关键词规则（用于自动分类与重要度打分）
CAT_RULES = {
    'notice': ['通知', '公告', '公示', '报名', '征集', '办法', '规定', '指南', '安排', '预告', '章程'],
    'academic': ['讲座', '论坛', '研讨', '学术', '论文', '研究', '团队', '成果', '学报', '讲坛', '报告', '大会'],
    'activity': ['艺术节', '比赛', '赛事', '运动会', '文艺', '演出', '社团', '志愿', '嘉年华', '开幕', '闭幕'],
    'party': ['党建', '党团', '党委', '支部', '党员', '主题教育', '思政', '红色', '党史'],
    'college': ['学院', '学部', '系所', '中心', '实验室', '书院'],
}
# 重要度打分：S=权威发布口或含强行政动作/截止日期；A=重要动态；B=常规资讯
LV_RULES = {
    'S': ['公示', '录取', '推免', '报名截止', '截止', '紧急', '重要', '必须',
          '特聘', '招聘公告', '国家', '重大', '改革', '章程', '办法', '规定', '任职', '公示期'],
    'A': ['获', '冠军', '第一', '入选', '获奖', '当选', '揭牌', '启用', '启动', '举办', '开幕',
          '特级', '晋升', '遴选', '招聘', '交流', '访问', '合作', '调整'],
}

# ---------------- HTTP ----------------
def fetch(url, retries=2):
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml',
                'Accept-Language': 'zh-CN,zh;q=0.9', 'Connection': 'close'})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
            for enc in ('utf-8', 'gb18030', 'gbk'):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode('utf-8', 'ignore')
        except Exception as e:
            if i == retries:
                print(f'    [失败] {url} -> {type(e).__name__}', file=sys.stderr)
                return None
            time.sleep(1.5 * (i + 1))
    return None


# ---------------- HTML 解析 ----------------
class ListParser(HTMLParser):
    """解析 VSB 列表页。

    支持两种结构：
    A) kydt.htm  — <li id="line_u6_0"><a href><h4>标题</h4><time>2026.10.12</time><p class="line3">摘要</p>
    B) bfxy.htm  — <li id="line_u7_0"><a href title="标题"><time><span>13</span>2026.10</time>
                  <h4><span>标题</span></h4><p class="line2">摘要</p>
    另有 <a title="..."> 属性可作标题兜底。
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items, self.cur = [], None
        self.cap = None
        self.buf = ''
        self.dm = ''          # <time> 内已抓到的文本
        self.ds = ''          # <time> 内 span 抓到的文本
        self.in_time_span = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'li' and a.get('id', '').startswith('line_'):
            self.cur = {'href': '', 'title': '', 'time': '', 'desc': '', 'title_attr': a.get('title', '') or ''}
        if self.cur is None:
            return
        if tag == 'a' and not self.cur['href']:
            self.cur['href'] = a.get('href', '')
            self.cur['title_attr'] = a.get('title', '') or self.cur['title_attr']
            self.cap = 'title'
        elif tag == 'h4':
            self.cap = 'title'
        elif tag == 'time':
            self.cap = 'time'
            self.dm, self.ds = '', ''
        elif tag == 'span' and self.cap == 'time':
            self.in_time_span = True
        elif tag == 'p':
            cls = a.get('class') or ''
            if 'line2' in cls or 'line3' in cls or 'line1' in cls:
                self.cap = 'desc'

    def handle_endtag(self, tag):
        if self.cur is None:
            return
        if tag == 'span':
            self.in_time_span = False
        if tag == 'time':
            # 组合两种日期形态：2026.10.12 / <span>13</span>2026.10
            raw = (self.ds + self.dm).strip()
            raw = re.sub(r'\s+', '', raw)
            if re.match(r'^\d{4}\.\d{1,2}\.\d{1,2}$', raw):
                self.cur['time'] = raw
            else:
                m = re.search(r'(\d{4})[.\-](\d{1,2})', raw)
                d = re.search(r'(\d{1,2})$', raw)
                if m and d:
                    self.cur['time'] = f'{m.group(1)}-{int(m.group(2)):02d}-{int(d.group(1)):02d}'
                else:
                    self.cur['time'] = raw
            self.dm, self.ds = '', ''
            self.cap = None
        elif tag in ('h4', 'p', 'a'):
            self.cap = None
        elif tag == 'li':
            self._flush()

    def handle_data(self, d):
        if self.cur is None or not self.cap:
            return
        if self.cap == 'time':
            if self.in_time_span:
                self.ds += d
            else:
                self.dm += d
        else:
            self.cur[self.cap] += d

    def _flush(self):
        t = clean(self.cur.get('title', '')) or clean(self.cur.get('title_attr', ''))
        self.cur['title'] = t
        self.cur['desc'] = clean(self.cur.get('desc', ''))
        if t:
            self.items.append(self.cur)
        self.cur = None

    def close(self):
        super().close()
        if self.cur:
            self._flush()


class TableParser(HTMLParser):
    """解析主站通知公告表格：<tr id="line_uX_N"><td><a>标题</a></td><td>单位</td><td>日期</td>"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items, self.row, self.cell = [], None, None
        self.stack = []
        self.buf = ''

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'tr' and a.get('id', '').startswith('line_'):
            self.row = {'href': '', 'title': '', 'org': '', 'time': ''}
        if self.row is None:
            return
        if tag == 'td':
            self.cell, self.buf = 'unknown', ''
        elif tag == 'a' and self.cell and not self.row['href']:
            self.row['href'] = a.get('href', '')
            self.cell = 'title'
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.row and tag == 'td' and self.cell:
            v = self.buf.strip()
            if self.cell == 'title':
                self.row['title'] = v
            elif v and re.match(r'\d{4}[-.]\d{1,2}[-.]\d{1,2}', v):
                self.row['time'] = v
            elif v and len(v) <= 30 and not self.row['org']:
                self.row['org'] = v
            self.cell, self.buf = None, ''
        if tag == 'tr' and self.row:
            if self.row.get('title'):
                self.items.append(self.row)
            self.row = None
        if self.stack:
            self.stack.pop()

    def handle_data(self, d):
        if self.cell:
            self.buf += d


def clean(s):
    return re.sub(r'\s+', ' ', (s or '')).strip()


def norm_date(s):
    s = clean(s).replace('/', '-').replace('.', '-')
    m = re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})', s)
    if m:
        return '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3)))
    m = re.search(r'(\d{4})(\d{2})(\d{2})', s)
    if m:
        return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    return ''


def abs_url(base, href):
    if not href:
        return ''
    if href.startswith('http'):
        return href
    return urllib.parse.urljoin(base, href)


# ---------------- 分类与打分 ----------------
def score_lv(title, desc, cat, col):
    """重要度打分：来源栏目权重 + 关键词命中。

    S=权威发布口或含强行政动作/截止日期
    A=重要动态（获奖、重要活动、人事招聘等）
    B=常规资讯
    """
    t = title + ' ' + desc

    # 通知公告栏内的条目天然更权威
    if col in ('通知公告', '武大要闻'):
        base = 'S' if any(k in t for k in LV_RULES['S']) else 'A'
    elif cat == 'notice':
        base = 'S' if any(k in t for k in LV_RULES['S']) else 'A'
    else:
        if any(k in t for k in LV_RULES['S']):
            base = 'S'
        elif any(k in t for k in LV_RULES['A']):
            base = 'A'
        else:
            base = 'B'

    # 有明确截止日期的提到S
    if re.search(r'截止|前完成|前提交|前报名|之前', t):
        base = 'S'
    return base


def guess_cat(title, src_cat, col=''):
    """分类：信源栏目优先，其次关键词匹配。"""
    if src_cat in CAT_RULES:
        return src_cat
    if col == '通知公告':
        return 'notice'
    for c, kws in CAT_RULES.items():
        if any(k in title for k in kws):
            return c
    return 'headline'


def guess_aud(title, desc, cat, col=''):
    """受众判定：教师向 / 学生向 / 师生通用"""
    t = title + ' ' + desc

    # 校级通知与要闻对全体师生皆有影响
    if cat == 'notice' or col in ('通知公告', '武大要闻', '综合新闻'):
        return 'both'

    teacher_kw = ['教师', '教职工', '辅导员', '教授', '院士', '团队', '科研', '论文',
                  '成果', '招聘', '职称', '人才', '党建', '支部', '党员', '学部', '教工',
                  '博士学位', '实验室', '学科', '导师', '教学', '学术']
    student_kw = ['学生', '本科生', '研究生', '新生', '开学', '课表', '考试', '选课',
                  '奖学金', '助学金', '艺术节', '运动会', '社团', '志愿', '班级', '学子',
                  '毕业生', '就业', '实习', '宿舍', ' campus', '青春']

    ts = any(k in t for k in teacher_kw)
    ss = any(k in t for k in student_kw)

    # 辅导员队伍相关归教师侧
    if '辅导员' in t and '学生' not in t:
        return 'tea'
    if cat == 'activity':
        return 'stu'
    if ts and not ss:
        return 'tea'
    if ss and not ts:
        return 'stu'
    if ts and ss:
        return 'both'
    return 'both'


def author_from(desc):
    m = re.search(r'(?:通讯员|记者)\s*([一-龥]{2,4})', desc or '')
    if m:
        pre = '通讯员' if '通讯员' in desc[:m.start() + 5] else '记者'
        return f'{pre} {m.group(1)}'
    m = re.search(r'记者\s*([一-龥]{2,4})', desc or '')
    if m:
        return f'记者 {m.group(1)}'
    return '记者团队'


# ---------------- 采集 ----------------
def collect(src, since):
    html = fetch(src['url'])
    if not html:
        return []
    html = re.sub(r'<!--.*?-->', '', html, flags=re.S)

    if src['mode'] == 'table':
        p = TableParser(); p.feed(html); raw = p.items
        for it in raw:
            it['desc'] = ''
            it['time'] = norm_date(it.get('time', ''))
    else:
        p = ListParser(); p.feed(html); raw = p.items
        for it in raw:
            it['title'] = clean(it.get('title', ''))
            it['desc'] = clean(it.get('desc', ''))
            it['time'] = norm_date(it.get('time', ''))
        raw = [it for it in raw if it['title']]

    out = []
    for it in raw:
        d = it.get('time', '')
        if not d or d < since:
            continue
        title = clean(it['title'])
        desc = clean(it.get('desc', ''))
        url = abs_url(src['url'], it.get('href', ''))
        if not title or not url:
            continue
        cat = guess_cat(title, src['cat'], src['col'])
        out.append(dict(
            id=hashlib.md5(url.encode()).hexdigest()[:12],
            t=title, d=d, c=cat, lv=score_lv(title, desc, cat, src['col']),
            aud=guess_aud(title, desc, cat, src['col']),
            org=clean(it.get('org', '')) or src['ch'],
            by=author_from(desc),
            col=src['col'], ch=src['ch'], url=url,
            s=desc[:120] or title,
            b=desc or title,
        ))
    return out


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'seen': []}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    state['seen'] = state['seen'][-800:]
    state['updated_at'] = datetime.now().isoformat(timespec='seconds')
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=45, help='采集最近多少天')
    ap.add_argument('--source', default='', help='仅采集指定 source key')
    args = ap.parse_args()

    since = (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')
    srcs = [s for s in SOURCES if s['key'] == args.source] if args.source else SOURCES

    print(f'开始采集，信源 {len(srcs)} 个，回溯至 {since}')
    state = load_state()
    seen = set(state.get('seen', []))
    all_items, errors = [], 0

    for s in srcs:
        print(f'  [{s["key"]}] {s["url"]}')
        try:
            items = collect(s, since)
            new = [i for i in items if i['id'] not in seen]
            for i in new:
                seen.add(i['id'])
            all_items += new
            print(f'    -> 解析 {len(items)} 条，新增 {len(new)} 条')
        except Exception as e:
            errors += 1
            print(f'    [错误] {type(e).__name__}: {e}', file=sys.stderr)
        time.sleep(1.2)

    all_items.sort(key=lambda x: x['d'], reverse=True)

    # 数据合并：与历史数据去重合并，避免重复运行时清空已有数据
    existing = []
    if os.path.exists(OUT_FILE):
        try:
            with open(OUT_FILE, encoding='utf-8') as f:
                prev = json.load(f)
            existing = prev.get('items', [])
        except Exception:
            existing = []

    if existing:
        merged = {i['id']: i for i in existing}
        for i in all_items:
            if i['id'] not in merged:
                merged[i['id']] = i
        out_items = sorted(merged.values(), key=lambda x: x['d'], reverse=True)
        # 仅保留最近一年，避免文件无限膨胀
        cutoff = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        out_items = [i for i in out_items if i['d'] >= cutoff]
    else:
        out_items = all_items

    # 保护：绝不写出空数据文件
    if not out_items:
        print('[保护] 无有效数据，保留原文件不变')
        return 0

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    payload = dict(
        updated_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
        count=len(out_items),
        sources=[dict(ch=s['ch'], col=s['col'], url=s['url']) for s in srcs],
        items=out_items,
    )
    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    state['seen'] = list(seen)
    save_state(state)

    print(f'\n采集完成：本次新增 {len(all_items)} 条，合并后共 {len(out_items)} 条，错误 {errors} 个')
    print(f'输出：{OUT_FILE}')
    print(f'日期区间：{out_items[-1]["d"]} ~ {out_items[0]["d"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
武汉大学校园资讯聚合 - REST API 服务

仅使用 Python 标准库（http.server + json），零第三方依赖。

启动：
  python api.py# 默认监听 0.0.0.0:8000
  python api.py --port 9000
  PORT=9000 python api.py        # 环境变量优先

接口一览：
  GET /api/health          健康检查
  GET /api/notices         资讯列表（筛选/排序/分页）
  GET /api/notices/{id}    资讯详情
  GET /api/categories      分类列表及计数
  GET /api/sources         信息来源列表
  GET /api/search?q=关键词关键词搜索
  GET /api/stats           数据统计
  GET /                    服务信息与接口索引
"""

import os
import re
import json
import time
import uuid
import threading
import argparse
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'data_news.json')

# 远程数据源：按优先级尝试，GitHub 仓库为唯一数据源。
# GitHub Actions 每次采集后提交新数据，API 运行时自动拉取，
# 这样无需重新部署即可让线上数据保持新鲜。
# 多个镜像轮换可用性，避免单一入口不可达导致数据停滞。
REMOTE_DATA_URLS = [
    u.strip() for u in os.environ.get('REMOTE_DATA_URLS', '').split(',') if u.strip()
] or [
    'https://ghproxy.net/https://raw.githubusercontent.com/tommyli731/whu-campus-news/main/data_news.json',
    'https://raw.githubusercontent.com/tommyli731/whu-campus-news/main/data_news.json',
    'https://cdn.jsdelivr.net/gh/tommyli731/whu-campus-news@main/data_news.json',
]
REMOTE_DATA_URL = REMOTE_DATA_URLS[0]
REMOTE_TIMEOUT = 15

API_VERSION = '1.1.0'
START_TIME = time.time()

# 可选鉴权：设置环境变量 API_KEY 后启用
#   Windows: set API_KEY=your-secret
#   Linux/mac: export API_KEY=your-secret
API_KEY = os.environ.get('API_KEY', '').strip()

CATEGORIES = {
    'headline': '要闻速览',
    'academic': '学术讲座',
    'notice': '通知公告',
    'college': '院系动态',
    'activity': '文体活动',
    'party': '党团思政',
}
AUDIENCES = {
    'stu': '仅学生',
    'tea': '仅教师',
    'both': '师生通用',
}
LEVELS = {
    'S': '重要（权威发布口）',
    'A': '较重要',
    'B': '常规',
}

_cache = {'key': None, 'data': None}
_lock = threading.Lock()
_CACHE_TTL = 300  # 远程数据缓存 5 分钟，避免高频请求打远程


_remote_status = {'last_ok': None, 'source': None, 'checked_at': None}


def fetch_remote():
    """从远程数据源拉取最新数据（多源轮换）。

    按 REMOTE_DATA_URLS 顺序尝试，第一个成功的即返回。
    全部失败返回 None，由调用方回退到本地数据。
    """
    if not REMOTE_DATA_URLS:
        return None
    for url in REMOTE_DATA_URLS:
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'WHU-Campus-News-Api/' + API_VERSION,
                'Accept': 'application/json',
            })
            with urllib.request.urlopen(req, timeout=REMOTE_TIMEOUT) as r:
                data = json.loads(r.read().decode('utf-8'))
            if isinstance(data, dict) and data.get('items'):
                _remote_status.update({'last_ok': url, 'source': url,
                                       'checked_at': datetime.now().strftime('%H:%M:%S')})
                print('  [数据] 远程拉取成功 %d 条 <- %s' % (len(data['items']), url[:64]))
                return data
        except Exception as e:
            print('  [数据] 远程源不可用 %s <- %s' % (type(e).__name__, url[:64]))
            continue
    return None


def load_local():
    if not os.path.exists(DATA_FILE):
        return None
    try:
        with open(DATA_FILE, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data.get('items') else None
    except Exception:
        return None


def load_data():
    """读取资讯数据。

    优先使用远程（GitHub）数据，保证自动更新；
    远程不可用时回退到本地文件。
    带 5 分钟缓存，避免每个请求都访问远程。
    """
    now = time.time()
    with _lock:
        if _cache['data'] is not None and (now - _cache['key']) < _CACHE_TTL:
            return _cache['data']

    remote = fetch_remote()
    local = load_local()

    # 两边都有时，取条目更多的（远程通常更新更全）
    if remote and local:
        chosen = remote if len(remote['items']) >= len(local['items']) else local
    else:
        chosen = remote or local

    if chosen:
        with _lock:
            _cache['key'] = now
            _cache['data'] = chosen
    return chosen


# ---------------- 业务逻辑 ----------------
def err(code, msg, detail=None):
    e = {'code': code, 'message': msg}
    if detail:
        e['detail'] = detail
    return e


def match_audience(n, aud):
    if not aud or aud == 'all':
        return True
    return n.get('aud') == aud or n.get('aud') == 'both'


def filter_items(items, category=None, audience=None, level=None, source=None,
                 since=None, until=None, keyword=None):
    out = []
    kw = (keyword or '').strip().lower()
    for n in items:
        if category and category != 'all' and n.get('c') != category:
            continue
        if not match_audience(n, audience):
            continue
        if level and level != 'all' and n.get('lv') != level:
            continue
        if source and source != 'all' and n.get('ch') != source:
            continue
        if since and n.get('d', '') < since:
            continue
        if until and n.get('d', '') > until:
            continue
        if kw:
            hay = ' '.join([
                n.get('t', ''), n.get('s', ''), n.get('b', ''),
                n.get('org', ''), n.get('by', ''), n.get('col', ''), n.get('ch', ''),
            ]).lower()
            if kw not in hay:
                continue
        out.append(n)
    return out


SORT_KEYS = {
    'date_desc':  lambda n: (_neg_date(n.get('d', '')), str(n.get('id', ''))),
    'date_asc':   lambda n: (n.get('d', ''), str(n.get('id', ''))),
    'level_desc': lambda n: ({'S': 3, 'A': 2, 'B': 1}.get(n.get('lv'), 0), n.get('d', '')),
    'title_asc':  lambda n: n.get('t', ''),
}


def _neg_date(d):
    """把日期转成可降序排列的字符串（大日期 -> 小字符串）。"""
    try:
        return str(99999999 - int(d.replace('-', '')))
    except Exception:
        return '99999999'


def sort_items(items, sort):
    """按指定规则排序。

    date_desc / level_desc 为降序：取负值后升序排列。
    date_asc / title_asc 为升序：直接排列。
    """
    if sort == 'date_desc':
        return sorted(items, key=lambda n: (_neg_date(n.get('d', '')),
                                            str(n.get('id', ''))))
    if sort == 'date_asc':
        return sorted(items, key=lambda n: (n.get('d', ''), str(n.get('id', ''))))
    if sort == 'level_desc':
        return sorted(items, key=lambda n: ({'S': 3, 'A': 2, 'B': 1}.get(n.get('lv'), 0),
                                            n.get('d', '')), reverse=True)
    if sort == 'title_asc':
        return sorted(items, key=lambda n: n.get('t', ''))
    return sorted(items, key=lambda n: (_neg_date(n.get('d', '')), str(n.get('id', ''))))


def brief(n):
    """列表项输出：精简字段，降低响应体积。"""
    return {
        'id': n.get('id'),
        'title': n.get('t'),
        'date': n.get('d'),
        'category': n.get('c'),
        'category_label': CATEGORIES.get(n.get('c'), n.get('c')),
        'level': n.get('lv'),
        'audience': n.get('aud'),
        'audience_label': AUDIENCES.get(n.get('aud'), n.get('aud')),
        'source_name': n.get('ch'),
        'source_column': n.get('col'),
        'summary': (n.get('s') or '')[:160],
        'url': n.get('url'),
    }


def full(n):
    """详情输出：含正文与完整来源信息。"""
    d = brief(n)
    d.update({
        'content': n.get('b'),
        'publisher': n.get('org'),
        'author': n.get('by'),
    })
    return d


# ---------------- 请求处理 ----------------
class Handler(BaseHTTPRequestHandler):
    server_version = f'WHUCampusNews/{API_VERSION}'
    protocol_version = 'HTTP/1.1'

    # ---- 基础工具 ----
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'X-API-Key, Content-Type')

    def send_json(self, obj, status=200, headers=None):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def send_error_json(self, status, code, message, detail=None, request_id=None):
        payload = {'success': False, 'error': err(code, message, detail)}
        if request_id:
            payload['request_id'] = request_id
        self.send_json(payload, status)

    def check_auth(self):
        """若配置了 API_KEY，则校验请求头。"""
        if not API_KEY:
            return True
        key = self.headers.get('X-API-Key', '')
        if key == API_KEY:
            return True
        # 也允许 ?api_key= 便于浏览器调试
        q = urllib.parse.urlparse(self.path).query
        qs = urllib.parse.parse_qs(q)
        if qs.get('api_key', [''])[0] == API_KEY:
            return True
        self.send_error_json(
            401, 'UNAUTHORIZED',
            '缺少或错误的 API Key',
            '请在请求头携带 X-API-Key: <your-key>，或在查询参数附加 ?api_key=<your-key>。'
            '服务未配置 API_KEY 环境变量时不校验。')
        return False

    def parse_qs(self):
        q = urllib.parse.urlparse(self.path).query
        return urllib.parse.parse_qs(q)

    def q1(self, qs, key, default=None):
        v = qs.get(key)
        return v[0] if v else default

    # ---- 路由 ----
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        rid = uuid.uuid4().hex[:12]
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'
        qs = self.parse_qs()

        try:
            if not self.check_auth():
                return

            if path == '/api/health':
                return self.handle_health(rid)
            if path == '/':
                return self.handle_index()
            if path == '/api':
                return self.handle_index()
            if path == '/api/notices':
                return self.handle_notices(qs, rid)
            if path == '/api/categories':
                return self.handle_categories(rid)
            if path == '/api/sources':
                return self.handle_sources(qs, rid)
            if path == '/api/search':
                return self.handle_search(qs, rid)
            if path == '/api/stats':
                return self.handle_stats(rid)

            m = re.match(r'^/api/notices/([^/]+)$', path)
            if m:
                return self.handle_notice_detail(urllib.parse.unquote(m.group(1)), rid)

            return self.send_error_json(
                404, 'NOT_FOUND', f'接口不存在: {path}',
                '请访问 GET / 查看接口索引。', rid)

        except BrokenPipeError:
            pass
        except Exception as e:
            self.send_error_json(
                500, 'INTERNAL_ERROR', '服务器内部错误',
                f'{type(e).__name__}: {e}', rid)

    # ---- 各接口实现 ----
    def handle_health(self, rid):
        data = load_data()
        local = load_local()
        remote_ok = _remote_status.get('last_ok') is not None
        self.send_json({
            'success': True,
            'data': {
                'status': 'ok' if data else 'degraded',
                'version': API_VERSION,
                'data_available': data is not None,
                'item_count': data.get('count', 0) if data else 0,
                'data_updated_at': data.get('updated_at') if data else None,
                'data_source': 'remote' if remote_ok else 'local',
                'remote_source': _remote_status.get('source'),
                'remote_checked_at': _remote_status.get('checked_at'),
                'local_item_count': len(local['items']) if local else 0,
                'uptime_seconds': round(time.time() - START_TIME, 1),
                'auth_required': bool(API_KEY),
                'server_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            },
            'request_id': rid,
        })

    def handle_index(self):
        self.send_json({
            'success': True,
            'data': {
                'name': '武汉大学校园资讯聚合 API',
                'version': API_VERSION,
                'description': '提供武汉大学各官方渠道资讯的查询接口。数据每日由 GitHub Actions 自动采集更新。',
                'data_source': REMOTE_DATA_URLS,
                'auto_update': '每日 08:00 与 18:00（北京时间）由 GitHub Actions 自动采集',
                'auth': {
                    'required': bool(API_KEY),
                    'type': 'API Key',
                    'header': 'X-API-Key',
                    'note': '服务端未配置 API_KEY 环境变量时不校验鉴权',
                },
                'endpoints': [
                    {'method': 'GET', 'path': '/api/health', 'desc': '健康检查'},
                    {'method': 'GET', 'path': '/api/notices', 'desc': '资讯列表'},
                    {'method': 'GET', 'path': '/api/notices/{id}', 'desc': '资讯详情'},
                    {'method': 'GET', 'path': '/api/categories', 'desc': '分类及计数'},
                    {'method': 'GET', 'path': '/api/sources', 'desc': '来源列表'},
                    {'method': 'GET', 'path': '/api/search', 'desc': '关键词搜索'},
                    {'method': 'GET', 'path': '/api/stats', 'desc': '数据统计'},
                ],
            },
        })

    def handle_notices(self, qs, rid):
        data = load_data()
        if not data:
            return self.send_error_json(
                503, 'DATA_UNAVAILABLE', '资讯数据暂不可用',
                '请先运行 python update.py 生成 data_news.json。', rid)

        category = self.q1(qs, 'category')
        audience = self.q1(qs, 'audience', 'all')
        level = self.q1(qs, 'level', 'all')
        source = self.q1(qs, 'source', 'all')
        since = self.q1(qs, 'since')
        until = self.q1(qs, 'until')
        keyword = self.q1(qs, 'q')
        sort = self.q1(qs, 'sort', 'date_desc')

        # 参数校验
        if category and category not in CATEGORIES and category != 'all':
            return self.send_error_json(
                400, 'INVALID_PARAM', f'category 取值非法: {category}',
                f'可选值：{", ".join(list(CATEGORIES.keys()) + ["all"])}', rid)
        if audience and audience not in AUDIENCES and audience != 'all':
            return self.send_error_json(
                400, 'INVALID_PARAM', f'audience 取值非法: {audience}',
                f'可选值：{", ".join(list(AUDIENCES.keys()) + ["all"])}', rid)
        if level and level not in LEVELS and level != 'all':
            return self.send_error_json(
                400, 'INVALID_PARAM', f'level 取值非法: {level}',
                f'可选值：{", ".join(list(LEVELS.keys()) + ["all"])}', rid)
        if sort not in SORT_KEYS:
            return self.send_error_json(
                400, 'INVALID_PARAM', f'sort 取值非法: {sort}',
                f'可选值：{", ".join(SORT_KEYS.keys())}', rid)
        for name, v in (('since', since), ('until', until)):
            if v and not re.match(r'^\d{4}-\d{2}-\d{2}$', v):
                return self.send_error_json(
                    400, 'INVALID_PARAM', f'{name} 日期格式非法: {v}',
                    '应为 YYYY-MM-DD，例如 2026-10-01。', rid)

        items = filter_items(data['items'], category, audience, level,
                             source, since, until, keyword)
        total = len(items)
        items = sort_items(items, sort)

        try:
            page = max(1, int(self.q1(qs, 'page', 1)))
            size = min(100, max(1, int(self.q1(qs, 'page_size', 20))))
        except ValueError:
            return self.send_error_json(
                400, 'INVALID_PARAM', 'page 或 page_size 不是合法整数',
                'page ≥ 1，page_size 取值 1~100。', rid)

        total_pages = (total + size - 1) // size if total else 0
        start = (page - 1) * size
        page_items = items[start:start + size]

        self.send_json({
            'success': True,
            'data': {
                'total': total,
                'page': page,
                'page_size': size,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'filters': {
                    'category': category or 'all',
                    'audience': audience,
                    'level': level,
                    'source': source,
                    'since': since,
                    'until': until,
                    'keyword': keyword or '',
                    'sort': sort,
                },
                'data_updated_at': data.get('updated_at'),
                'items': [brief(n) for n in page_items],
            },
            'request_id': rid,
        })

    def handle_notice_detail(self, nid, rid):
        data = load_data()
        if not data:
            return self.send_error_json(
                503, 'DATA_UNAVAILABLE', '资讯数据暂不可用', None, rid)
        for n in data['items']:
            if str(n.get('id')) == nid:
                return self.send_json({
                    'success': True,
                    'data': full(n),
                    'request_id': rid,
                })
        return self.send_error_json(
            404, 'NOTICE_NOT_FOUND', f'未找到 id 为 {nid} 的资讯',
            '请通过 GET /api/notices 获取有效 id 列表。', rid)

    def handle_categories(self, rid):
        data = load_data()
        if not data:
            return self.send_error_json(
                503, 'DATA_UNAVAILABLE', '资讯数据暂不可用', None, rid)
        counts = {}
        for n in data['items']:
            counts[n.get('c')] = counts.get(n.get('c'), 0) + 1
        self.send_json({
            'success': True,
            'data': {
                'total': len(data['items']),
                'items': [
                    {'key': k, 'label': v, 'count': counts.get(k, 0)}
                    for k, v in CATEGORIES.items()
                ],
            },
            'request_id': rid,
        })

    def handle_sources(self, qs, rid):
        data = load_data()
        if not data:
            return self.send_error_json(
                503, 'DATA_UNAVAILABLE', '资讯数据暂不可用', None, rid)
        group = {}
        for n in data['items']:
            k = n.get('ch') or '未知来源'
            g = group.setdefault(k, {'name': k, 'item_count': 0,
                                     'columns': {}, 'latest_date': ''})
            g['item_count'] += 1
            col = n.get('col') or '未分类'
            g['columns'][col] = g['columns'].get(col, 0) + 1
            if n.get('d', '') > g['latest_date']:
                g['latest_date'] = n.get('d', '')
        out = []
        for g in group.values():
            g['columns'] = [{'name': k, 'count': v}
                            for k, v in sorted(g['columns'].items(),
                                               key=lambda x: -x[1])]
            out.append(g)
        out.sort(key=lambda x: (-x['item_count'], x['name']))
        self.send_json({
            'success': True,
            'data': {'total': len(out), 'items': out},
            'request_id': rid,
        })

    def handle_search(self, qs, rid):
        data = load_data()
        if not data:
            return self.send_error_json(
                503, 'DATA_UNAVAILABLE', '资讯数据暂不可用', None, rid)
        q = (self.q1(qs, 'q') or self.q1(qs, 'keyword') or '').strip()
        if not q:
            return self.send_error_json(
                400, 'MISSING_PARAM', '缺少必填参数 q',
                '用法：GET /api/search?q=讲座', rid)
        try:
            size = min(100, max(1, int(self.q1(qs, 'page_size', 20))))
        except ValueError:
            return self.send_error_json(
                400, 'INVALID_PARAM', 'page_size 不是合法整数', None, rid)

        items = filter_items(data['items'], keyword=q)
        items = sort_items(items, 'date_desc')
        total = len(items)
        self.send_json({
            'success': True,
            'data': {
                'keyword': q,
                'total': total,
                'items': [brief(n) for n in items[:size]],
                'fields_searched': ['标题', '摘要', '正文', '发布机构', '作者', '栏目', '来源'],
            },
            'request_id': rid,
        })

    def handle_stats(self, rid):
        data = load_data()
        if not data:
            return self.send_error_json(
                503, 'DATA_UNAVAILABLE', '资讯数据暂不可用', None, rid)
        items = data['items']
        by_cat, by_level, by_aud, by_date = {}, {}, {}, {}
        for n in items:
            by_cat[n.get('c')] = by_cat.get(n.get('c'), 0) + 1
            by_level[n.get('lv')] = by_level.get(n.get('lv'), 0) + 1
            by_aud[n.get('aud')] = by_aud.get(n.get('aud'), 0) + 1
            by_date[n.get('d')] = by_date.get(n.get('d'), 0) + 1
        dates = [n.get('d') for n in items if n.get('d')]
        self.send_json({
            'success': True,
            'data': {
                'total': len(items),
                'date_range': {'from': min(dates), 'to': max(dates)} if dates else None,
                'updated_at': data.get('updated_at'),
                'by_category': [{'key': k, 'label': CATEGORIES.get(k, k), 'count': v}
                                for k, v in sorted(by_cat.items(), key=lambda x: -x[1])],
                'by_level': [{'level': k, 'label': LEVELS.get(k, k), 'count': v}
                             for k, v in sorted(by_level.items())],
                'by_audience': [{'key': k, 'label': AUDIENCES.get(k, k), 'count': v}
                                for k, v in sorted(by_aud.items(), key=lambda x: -x[1])],
                'source_count': len({n.get('ch') for n in items}),
            },
            'request_id': rid,
        })

    def log_message(self, fmt, *args):
        ts = datetime.now().strftime('%H:%M:%S')
        print(f'[{ts}] {self.address_string()} {fmt % args}')


def main():
    ap = argparse.ArgumentParser(description='武汉大学校园资讯聚合 API')
    ap.add_argument('--port', type=int, default=int(os.environ.get('PORT', 8000)))
    ap.add_argument('--host', default=os.environ.get('HOST', '0.0.0.0'))
    args = ap.parse_args()

    data = load_data()
    print('=' * 56)
    print('武汉大学校园资讯聚合 API')
    print('=' * 56)
    print(f'版本     : {API_VERSION}')
    print(f'监听: http://{args.host}:{args.port}')
    print(f'数据     : {"已加载 " + str(data["count"]) + " 条" if data else "未加载（请先运行 update.py）"}')
    print(f'鉴权     : {"已启用（X-API-Key）" if API_KEY else "未启用（公开访问）"}')
    if data:
        print(f'更新时间 : {data.get("updated_at")}')
    print('=' * 56)
    print('接口索引 : GET /')
    print('按 Ctrl+C 停止')
    print('=' * 56)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n正在关闭…')
        srv.shutdown()


if __name__ == '__main__':
    main()
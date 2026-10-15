#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号文章速查工具

用途：在命令行快速搜索微信公众号文章，输出标题、日期、来源与原文链接。
       适合临时查询「某个公众号最近发了什么」，不做定时采集。

⚠️ 使用须知
- 本工具仅供个人临时查阅，每次手动运行，不做持续抓取
- 搜狗 Robots 协议禁止自动化批量采集，请勿高频调用
- 每次查询间隔已内置限流，连续查询过多会触发验证码
- 文章版权归原作者，本工具仅输出标题与链接

用法：
  python tools/search_wechat.py武汉大学
  python tools/search_wechat.py 武大 讲座 --pages 2
  python tools/search_wechat.py "选课" --open        # 查完自动打开浏览器
"""

import os
import re
import sys
import time
import json
import html
import argparse
import urllib.request
import urllib.error
import urllib.parse
import webbrowser

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
SOGOU = 'https://weixin.sogou.com'
TIMEOUT = 20

# 限流：每次请求间隔（秒），避免触发风控
DELAY = 4.0


def fetch(url, referer=None):
    """发起请求。referer 必填，否则搜狗会拒绝。"""
    h = {'User-Agent': UA,
         'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
         'Accept-Language': 'zh-CN,zh;q=0.9'}
    if referer:
        h['Referer'] = referer
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
        for enc in ('utf-8', 'gbk', 'gb18030'):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode('utf-8', 'ignore')
    except Exception as e:
        print(f'  [请求失败] {type(e).__name__}: {e}', file=sys.stderr)
        return None


def strip_tags(s):
    s = re.sub(r'<[^>]+>', '', s or '')
    return html.unescape(s).strip()


def parse_results(page):
    """解析搜狗搜索结果页。

    搜狗当前的结果结构（实测2026-10）：
      <div class="txt-box">
        <h3><a href="/link?url=...">标题</a></h3>
        <p class="txt-info">摘要</p>
        <div class="s-p">
          <span class="all-time-y2">公众号名</span>
          <span class="s2"><script>timeConvert('1768906676')</script></span>
        </div>
      </div>
    """
    if not page:
        return []

    # 风控检测
    if 'antispider' in page or '请输入验证码' in page or '用户您好' in page:
        print('  [⚠] 触发搜狗反爬拦截，请稍后再试或降低查询频率', file=sys.stderr)
        return []

    items = []
    blocks = re.findall(r'<div class="txt-box">(.*?)</li>', page, re.S)
    if not blocks:
        blocks = re.findall(r'<div class="txt-box">(.*?)(?=<div class="txt-box">|$)', page, re.S)

    for b in blocks:
        m = re.search(r'<h3>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
        if not m:
            continue
        url, title = m.group(1), strip_tags(m.group(2))

        # 公众号名：在 s-p 块的 all-time-y2 里
        mp = ''
        mm = re.search(r'<span class="all-time-y2[^"]*">(.*?)</span>', b, re.S)
        if mm:
            mp = strip_tags(mm.group(1))

        # 日期：timeConvert('时间戳')
        date = ''
        d = re.search(r"timeConvert\('(\d+)'\)", b)
        if d:
            date = time.strftime('%Y-%m-%d', time.localtime(int(d.group(1))))

        # 摘要
        summary = ''
        s = re.search(r'<p class="txt-info"[^>]*>(.*?)</p>', b, re.S)
        if s:
            summary = strip_tags(s.group(1))

        if title:
            items.append({'title': title, 'url': url, 'date': date,
                          'mp': mp, 'summary': summary[:80]})
    return items


def search(keyword, pages=1):
    """搜索关键词，返回结果列表。"""
    kw = urllib.parse.quote(keyword)
    all_items = []

    for p in range(1, pages + 1):
        url = f'{SOGOU}/weixin?type=2&query={kw}&page={p}'
        if p > 1:
            print(f'  翻页 {p}/{pages}…')
            time.sleep(DELAY)

        page = fetch(url, referer=f'{SOGOU}/')
        if not page:
            break

        items = parse_results(page)
        if not items:
            if p == 1:
                print('  未找到结果，可能触发风控或关键词无结果', file=sys.stderr)
            break

        all_items += items
        time.sleep(DELAY)

    # 去重
    seen, uniq = set(), []
    for it in all_items:
        k = it['title']
        if k not in seen:
            seen.add(k)
            uniq.append(it)
    return uniq


def print_result(items, keyword):
    if not items:
        print(f'\n没有找到与「{keyword}」相关的文章。')
        print('换个关键词试试，或到搜狗网页版搜索：https://weixin.sogou.com')
        return

    print()
    print('=' * 74)
    print(f'「{keyword}」共找到 {len(items)} 条相关文章')
    print('=' * 74)

    for i, it in enumerate(items, 1):
        print()
        print(f'{i}. {it["title"]}')
        meta = []
        if it['mp']:
            meta.append(it['mp'])
        if it['date']:
            meta.append(it['date'])
        if meta:
            print(f'   {"　|　".join(meta)}')
        if it['summary']:
            print(f'   摘要：{it["summary"]}')

    print()
    print('=' * 74)
    print('以上为标题与摘要。')
    print('查看原文：用 --open 参数，或手动访问 https://weixin.sogou.com 搜索相同关键词')
    print('  （搜狗跳转链含一次性 token，会很快过期，故不直接展示）')


def save_json(items, keyword, path):
    """保存为 JSON，便于二次处理。"""
    data = {'keyword': keyword, 'count': len(items),
            'queried_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'items': items}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'\n已保存到：{path}')


def main():
    ap = argparse.ArgumentParser(
        description='微信公众号文章速查（个人临时查询，不做持续采集）',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('keyword', nargs='?', help='搜索关键词，如「武汉大学」')
    ap.add_argument('--pages', type=int, default=1, help='翻页数，默认 1')
    ap.add_argument('--json', metavar='路径', help='同时保存为 JSON')
    ap.add_argument('--open', action='store_true', help='用浏览器打开搜狗搜索页')
    ap.add_argument('--list', action='store_true', help='列出建议关键词')
    args = ap.parse_args()

    if args.list or not args.keyword:
        print(__doc__)
        print('\n常用关键词建议：')
        for k in ['武汉大学', '珞珈讲坛', '武大 通知', '武大 讲座', '武大 学术', '教务 通知']:
            print(f'  python tools/search_wechat.py "{k}"')
        print()
        return 0

    print(f'正在搜索「{args.keyword}」…')
    try:
        items = search(args.keyword, args.pages)
    except KeyboardInterrupt:
        print('\n已取消')
        return 130

    print_result(items, args.keyword)

    if args.json:
        save_json(items, args.keyword, args.json)

    if args.open:
        u = f'{SOGOU}/weixin?type=2&query={urllib.parse.quote(args.keyword)}'
        print(f'\n已在浏览器打开：{u}')
        webbrowser.open(u)

    return 0 if items else 1


if __name__ == '__main__':
    sys.exit(main())
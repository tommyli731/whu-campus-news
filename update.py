#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键更新：采集数据 → 写入 data_news.json

用��：
  python update.py                # Windows 双击运行
  python update.py --days 60      # 自定义回溯天数

建议加入系统定时任务（Windows 任务计划程序）：
  每天 08:00 和 18:00 各执行一次
"""

import subprocess, sys, os, shutil, json
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CRAWLER = os.path.join(HERE, 'crawler', 'crawler.py')
TARGET = os.path.join(HERE, 'data_news.json')


def main():
    days = '60'
    if '--days' in sys.argv:
        days = sys.argv[sys.argv.index('--days') + 1]

    print('=' * 46)
    print('武汉大学校园资讯聚合 · 数据更新')
    print('时间:', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print('=' * 46)

    py = sys.executable
    r = subprocess.run([py, CRAWLER, '--days', days], capture_output=True, text=True, encoding='utf-8')
    print(r.stdout)
    if r.returncode != 0:
        print('[警告] 采集未获得新数据，保留原有 data_news.json')
        if r.stderr:
            print(r.stderr[:500])

    src = os.path.join(HERE, 'crawler', 'data', 'news.json')
    need_copy = True
    if os.path.exists(TARGET) and os.path.exists(src):
        need_copy = os.path.getmtime(src) > os.path.getmtime(TARGET)

    if need_copy and os.path.exists(src):
        shutil.copyfile(src, TARGET)
        with open(TARGET, encoding='utf-8') as f:
            d = json.load(f)
        print(f'\n[完成] 已更新 data_news.json，共 {d["count"]} 条，'
              f'更新时间 {d["updated_at"]}')
    else:
        print('\n[跳过] 无新数据，data_news.json 未变动')

    print('=' * 46)


if __name__ == '__main__':
    main()
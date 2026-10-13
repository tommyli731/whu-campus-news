#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
版本化发布工具

用途：每次更新后自动完成版本留痕三件事
  1. 为当前版本建立独立快照（snapshots/vX.Y-描述/）
  2. 在「版本存档记录.md」追加一节
  3. 输出本次应使用的线上地址

用法：
  python release.py --ver1.5 --desc "接入微信公众号采集"
  python release.py --ver 1.5 --desc "说明文字" --data     # 同时运行爬虫更新数据
"""

import os, sys, json, shutil, subprocess, argparse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(HERE, 'snapshots')
LOG_FILE = os.path.join(HERE, '版本存档记录.md')
DATA = os.path.join(HERE, 'data_news.json')
INDEX = os.path.join(HERE, 'index.html')


def read_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding='utf-8') as f:
            return f.read()
    return '# 版本存档记录\n'


def data_stat():
    if not os.path.exists(DATA):
        return '无数据文件'
    try:
        with open(DATA, encoding='utf-8') as f:
            d = json.load(f)
        return f"{d['count']} 条 / 更新于 {d['updated_at']}"
    except Exception as e:
        return f'读取失败: {e}'


def snapshot(ver, desc):
    name = f'v{ver}'
    path = os.path.join(SNAP_DIR, name)
    os.makedirs(path, exist_ok=True)

    files = []
    for f in os.listdir(HERE):
        p = os.path.join(HERE, f)
        if os.path.isfile(p) and f.endswith(('.html', '.json')) and not f.startswith('.'):
            shutil.copyfile(p, os.path.join(path, f))
            files.append(f)

    # 附一份说明，单独打开快照也能看懂
    with open(os.path.join(path, '说明.txt'), 'w', encoding='utf-8') as f:
        f.write(f"版本：v{ver}\n")
        f.write(f"说明：{desc}\n")
        f.write(f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"数据：{data_stat()}\n")
        f.write(f"文件：{', '.join(files)}\n\n")
        f.write("本快照可独立打开：双击 index.html即可浏览。\n")
    return path, files


def append_log(ver, desc, files, extra=''):
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    entry = f"""
### v{ver} — {now}
{desc}

- 快照位置：`snapshots/v{ver}/`
- 快照文件：{', '.join(files)}
- 数据状态：{data_stat()}
{extra}
---
"""
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(entry)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ver', required=True, help='版本号，如 1.5')
    ap.add_argument('--desc', required=True, help='本版变更说明')
    ap.add_argument('--data', action='store_true', help='发布前先运行爬虫')
    args = ap.parse_args()

    print('=' * 54)
    print(f'版本化发布  v{args.ver}')
    print('=' * 54)

    if args.data:
        print('\n[1/3] 运行爬虫更新数据…')
        r = subprocess.run([sys.executable, os.path.join(HERE, 'update.py')],
                           capture_output=True, text=True, encoding='utf-8')
        print(r.stdout[-600:] if r.stdout else '(无输出)')

    if not os.path.exists(INDEX):
        print('[错误] 未找到 index.html')
        return 1

    print(f'\n[2/3] 建立快照 v{args.ver}…')
    path, files = snapshot(args.ver, args.desc)
    print(f'      → {path}')
    print(f'      → 文件：{", ".join(files)}')

    print('\n[3/3] 追加版本记录…')
    append_log(args.ver, args.desc, files)
    print('      → 版本存档记录.md 已更新')

    print('\n' + '=' * 54)
    print('版本留痕完成')
    print('=' * 54)
    print(f'快照目录：snapshots/v{args.ver}/')
    print(f'数据状态：{data_stat()}')
    print()
    print('关于线上地址：')
    print('  平台限制：同一账号下重复发布会覆盖同一域名，无法生成新网址。')
    print('  线上入口：https://whu-campus-news.app.workbuddy.host/（始终为最新版）')
    print('  如需历史版本独立可访问，需部署到独立托管平台，或用不同账号发布。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
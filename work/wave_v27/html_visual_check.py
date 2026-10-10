"""独立したヘッドレスブラウザで、ローカル報告の表示を保存する。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
REPORT = HERE.parents[1] / 'アルゴリズム調査' / '00022_中期方向と板の入口を分離'


def main() -> None:
    """機能: 報告HTMLの実描画と描画後DOMを、利用者とは別のブラウザ領域へ保存する。

    引数: names (list[str]) は報告フォルダ内のHTML名。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('names', nargs='+')
    args = parser.parse_args()
    browser = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    results = []
    for index, name in enumerate(args.names):
        source = (REPORT / name).resolve()
        assert source.parent == REPORT.resolve() and source.exists()
        screenshot = HERE / ('表示検査_' + source.stem + '.png')
        profile = HERE / f'browser_qa_{index}'
        command = [str(browser), '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                   '--disable-background-networking', '--disable-component-update', '--disable-sync',
                   '--disable-default-apps', '--disable-features=MediaRouter,OptimizationHints',
                   '--hide-scrollbars', '--window-size=1440,1100', '--virtual-time-budget=1200',
                   '--user-data-dir=' + str(profile), '--screenshot=' + str(screenshot), '--dump-dom', source.as_uri()]
        completed = subprocess.run(command, capture_output=True, timeout=50, creationflags=subprocess.CREATE_NO_WINDOW)
        assert completed.returncode == 0, completed.stderr[-1500:]
        dom = completed.stdout.decode('utf-8', errors='replace')
        (HERE / ('表示検査_' + source.stem + '.html')).write_text(dom, encoding='utf-8')
        assert screenshot.exists() and screenshot.stat().st_size > 10000
        if source.stem == '５分足と売買':
            assert '決済 ' in dom and 'チャートは再生上の約定値を' in dom, 'JavaScriptによる初回描画を確認できません'
        results.append({'ファイル': name, 'PNG': screenshot.name, '画像バイト': screenshot.stat().st_size, '描画後DOM保存': True})
    (HERE / 'html_visual_check.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

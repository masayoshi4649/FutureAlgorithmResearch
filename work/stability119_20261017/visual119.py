"""公開予定の静的レポートを隔離Chromeで描画し、暗色と横スクロールを確認する。"""

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess


def render(path: Path, output: Path, width: int) -> dict:
    """
    機能: 実ユーザーのブラウザ状態を変更せず、一画面の描画とDOM検査を保存する。
    引数: path(Path) は完成HTML、output(Path) は新規画像先、width(int) は表示幅。
    返り値: dict は検査結果と画像指紋。市場データや外部通信は使わない。
    """
    output.mkdir(parents=True, exist_ok=False)
    source = path.read_text(encoding='utf-8')
    script = '''<script>
    /**
     * 機能: 完成した表と暗色表示を検査する。
     * 引数: なし。
     * 返り値: なし。結果をbodyの属性へ保存する。
     */
    window.addEventListener('load', () => {
      const bg = getComputedStyle(document.body).backgroundColor;
      const parts = bg.match(/[0-9.]+/g).map(Number);
      const result = {
        title: document.querySelector('h1')?.textContent,
        tables: document.querySelectorAll('table').length,
        rows: document.querySelectorAll('tr[data-session]').length,
        dark: parts.slice(0,3).reduce((a,b)=>a+b,0) < 180,
        viewport: innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth + 1
      };
      document.body.dataset.visual = JSON.stringify(result);
    });
    </script>'''
    target = output / '画面.html'
    assert source.count('</body>') == 1
    target.write_text(source.replace('<head>', '<head><base href="' + path.parent.as_uri() + '/">', 1).replace('</body>', script + '</body>'), encoding='utf-8')
    picture = output / '画面.png'
    command = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '--headless=new', '--disable-gpu',
               '--no-first-run', '--disable-background-networking', '--disable-component-update', '--disable-sync',
               '--run-all-compositor-stages-before-draw', '--disable-features=PaintHolding',
               '--proxy-server=http://127.0.0.1:9', f'--window-size={width},1800', '--virtual-time-budget=1800',
               '--user-data-dir=' + str(output / 'profile'), '--screenshot=' + str(picture), '--dump-dom', target.as_uri()]
    process = subprocess.run(command, capture_output=True, timeout=55, creationflags=subprocess.CREATE_NO_WINDOW)
    (output / '描画stderr.txt').write_bytes(process.stderr)
    assert process.returncode == 0 and picture.exists()
    found = re.search(r'<body\b[^>]*\bdata-visual="([^"]*)"', process.stdout.decode('utf-8', errors='replace'))
    assert found
    result = json.loads(html.unescape(found.group(1)))
    assert result['dark'] and not result['horizontalOverflow'] and result['tables'] > 0
    result.update(image=picture.as_posix(), image_SHA256=hashlib.sha256(picture.read_bytes()).hexdigest(),
                  source_SHA256=hashlib.sha256(path.read_bytes()).hexdigest(), viewed_by_root=False)
    (output / '描画検査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('html', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--width', type=int, default=1450)
    args = parser.parse_args()
    print(json.dumps(render(args.html.resolve(), args.out.resolve(), args.width), ensure_ascii=False))

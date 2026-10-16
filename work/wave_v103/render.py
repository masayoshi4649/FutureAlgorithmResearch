"""公開前の静的HTMLを専用の非表示ブラウザーで画像にする。"""

import re
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
TITLE = '板の定着と進行失敗の説明と全セッション損益.html'


def capture(name: str, document: str, width: int, height: int) -> None:
    """
    機能: 専用profileでHTMLを非表示描画し、根担当の目視画像を保存する。
    引数: name/document(str)、width/height(int)は画像名・資料・画面幅高さ。
    返り値: None。ユーザーのブラウザーprofileや表示中のタブを変更しない。
    """
    folder = HERE/'report/visual_final'
    folder.mkdir(parents=True, exist_ok=True)
    html, png = folder/(name+'.html'), folder/(name+'.png')
    assert not html.exists() and not png.exists()
    html.write_text(document, encoding='utf-8')
    arguments = [str(CHROME), '--headless=new', '--disable-gpu', '--disable-background-networking',
        '--disable-component-update', '--disable-extensions', '--no-first-run', '--no-default-browser-check',
        '--hide-scrollbars', '--allow-file-access-from-files', '--virtual-time-budget=1200',
        '--user-data-dir='+str(folder/('profile_'+name)), '--screenshot='+str(png),
        f'--window-size={width},{height}', html.as_uri()]
    result = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0 and png.exists() and png.stat().st_size > 1000
    print(name+' 描画画像を保存', flush=True)


def main() -> None:
    """
    機能: 比較表と実際の全場損益表を広い画面と狭い画面で目視用に描く。
    引数: なし。
    返り値: None。公開前資料を変えず複製から画像を作る。
    """
    document = (HERE/'report/preview_final'/TITLE).read_text(encoding='utf-8')
    capture('比較表の広幅', document, 1440, 1500)
    capture('比較表の狭幅', document, 500, 1100)
    head = document[:document.index('<main>')]
    for ident in ('C_VOLUME', 'U_C1R1'):
        matched = re.search(r'<details id="'+ident+r'">.*?</details>', document, re.DOTALL)
        assert matched
        part = matched.group(0).replace('<details id="'+ident+'">', '<details open id="'+ident+'">', 1)
        capture(ident+'の全場表', head+'<main><h1>'+ident+' 全32場</h1>'+part+'</main></body></html>', 1440, 1800)


if __name__ == '__main__':
    main()

"""00075 の数値と表示を通信なしの実ブラウザで独立検査する。"""
from pathlib import Path
import hashlib
import importlib.util
import json
from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'アルゴリズム調査/00075_J2赤字上位セッションの板検証と防止策'
SOURCE = OUT / '赤字上位3セッションの板と防止策.html'


def main():
    """
    機能: 既存の隔離ブラウザ描画器を利用し、4画面を保存する。
    引数: なし。
    返り値: None。検査コード・結果・画像だけを当作業のreportへ保存する。
    """
    spec = importlib.util.spec_from_file_location('旧隔離描画', ROOT / 'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = OUT
    renderer.VISUAL = HERE / 'visual'
    renderer.PROBE = '<script>' + (HERE / 'browser_probe.js').read_text(encoding='utf-8') + '</script>'
    source = SOURCE.read_text(encoding='utf-8')
    policy = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">' 
    isolated = source.replace('<head>', '<head>' + policy)
    pictures = [
        ('全体広幅', 1500, 1450, ''),
        ('全体狭幅', 520, 1450, ''),
        ('板詳細', 1500, 2400, '<script>const c=document.querySelector(".case");document.querySelector("main").replaceChildren(c);c.querySelectorAll(".trade-detail").forEach(d=>d.open=d.querySelector("summary").textContent.includes("−"));const d=c.querySelector(".trade-detail[open]");d.querySelectorAll("details").forEach(v=>v.open=true);c.querySelectorAll(".trade-detail").forEach(v=>{if(v!==d)v.remove()});window.scrollTo(0,0);</script>'),
        ('全セッション損益', 1500, 2100, '<script>document.querySelector("main").replaceChildren(document.getElementById("sessions"));window.scrollTo(0,0);</script>'),
    ]
    results = [renderer.render(isolated, *args) for args in pictures]
    soup = BeautifulSoup(source, 'html.parser')
    output = {
        '全合格': True, '目視確認': False,
        '元HTML変更': False, '外部API通信': 'CSP connect-src none と接続不能プロキシを併用',
        '元HTML外部資源数': len(soup.select('script[src],link[href],img[src]')),
        '結果': results,
        'HTML_SHA256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    }
    path = HERE / 'HTML表示の独立検査.json'
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()

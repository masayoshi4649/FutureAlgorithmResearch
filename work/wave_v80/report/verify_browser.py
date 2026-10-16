"""主HTMLと全330条件HTMLを外部通信なしの実ブラウザで独立検査する。"""
from pathlib import Path
import hashlib
import importlib.util
import json
from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=HERE.parents[2]
OUT=ROOT/'アルゴリズム調査/00076_5秒発注遅延を含む秒スキャルピング'
MAIN=OUT/'秒スキャルピングの改善と全セッション損益.html'
ALL=OUT/'全330条件の前半比較.html'


def embedded(path):
    """
    機能: 表示用資料を原HTMLから読み出す。
    引数: path (Path)。
    返り値: tuple[str, dict] のHTMLと埋込JSON。
    """
    source=path.read_text(encoding='utf-8')
    return source,json.loads(BeautifulSoup(source,'html.parser').select_one('#report-data').string)


# ----------------------------------------
def main():
    """
    機能: 埋込JSONを保存会計と照合後、切替・絞込・表示を実ブラウザで確かめる。
    引数: なし。
    返り値: None。検査用複製・PNG・検査結果だけをreportに書く。
    """
    frozen_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (MAIN,ALL)}
    source,data=embedded(MAIN);other,all_data=embedded(ALL)
    files=0
    for delay,methods in data['final'].items():
        for identifier,result in methods.items():
            saved=json.loads((BASE/f'final/delay{delay}/results/{identifier}.json').read_text(encoding='utf-8'))
            assert saved==result;files+=1
    for row in all_data['rows']:
        stage='first' if row['stage']=='初回' else 'repair'
        saved=json.loads((BASE/stage/'results'/(row['config']['id']+'.json')).read_text(encoding='utf-8'))
        assert row['config']==saved['config'] and row['metrics']==saved['periods']['前16'];files+=1
    spec=importlib.util.spec_from_file_location('旧隔離描画',ROOT/'work/wave_v52/review/verify_report.py')
    renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
    renderer.OUT=OUT;renderer.VISUAL=HERE/'visual'
    renderer.PROBE='<script>'+(HERE/'browser_probe.js').read_text(encoding='utf-8')+'</script>'
    policy='<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">'
    error_capture='<script>window.browserErrors=[];window.addEventListener("error",e=>window.browserErrors.push(e.message));window.addEventListener("unhandledrejection",e=>window.browserErrors.push(String(e.reason)));</script>'
    isolated=source.replace('<head>','<head>'+policy+error_capture)
    isolated_all=other.replace('<head>','<head>'+policy+error_capture)
    pictures=[(isolated,'主全体広幅',1500,1500,''),(isolated,'主全体狭幅',520,1450,''),
              (isolated,'全セッション損益',1500,2000,'<script>document.querySelector("main").replaceChildren(document.getElementById("all-sessions"));window.scrollTo(0,0);</script>'),
              (isolated,'損失原因と待ち時間',1500,2200,'<script>const detail=[...document.querySelectorAll("details")].find(d=>d.querySelector("summary").textContent.startsWith("損失の原因"));detail.open=true;document.querySelector("main").replaceChildren(detail);window.scrollTo(0,0);</script>'),
              (isolated_all,'全330広幅',1500,1400,''),(isolated_all,'全330狭幅',520,1400,'')]
    results=[renderer.render(*args) for args in pictures]
    assert frozen_hashes=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (MAIN,ALL)},'描画中にHTMLが変更された'
    output=dict(全合格=True,目視確認=False,原HTML変更=False,埋込会計独立一致ファイル数=files,
                外部通信='複製CSP connect-src none と接続不能proxyで禁止',結果=results,
                HTML_SHA256=frozen_hashes)
    target=HERE/'HTML表示の独立検査.json';target.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False))


if __name__=='__main__': main()

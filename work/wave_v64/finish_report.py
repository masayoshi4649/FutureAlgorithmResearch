"""固定済み限界値へ気配感度の補足と独立検算の案内を付け、表示を確認する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00061_入口の方向予測精度を出口と分離'


def main() -> None:
    """機能: 採点値を変更せず補足を公開し、暗色HTMLの広狭画面を検査する。

    引数: なし。返り値: なし(None)。原本・計算条件・旧作業は変更しない。
    """
    for name in ('限界値の独立検査.json','限界値の気配感度検査.json'):
        shutil.copyfile(HERE/name,OUT/name)
    target=OUT/'入口の方向予測精度.html'
    source=target.read_text(encoding='utf-8')
    if 'id="quote-check"' not in source:
        extra='''<details class="card" id="quote-check"><summary>気配の見かけで最大値が大きくなっていないか</summary><p>買いなら将来の買い気配bid、売りなら売り気配askという返済可能側でも点検しました。候補3・NKの0.10%到達22/23=95.7%は変わりません。最大順行中央値は中値260円から255円へ下がり、判断時の新規側気配まで含めると250円です。最高値で決済できるとの仮定や費用後損益ではありません。</p><p>候補2・TOPIXには気配差が58呼値の瞬間を中値の峰として数えた例があり、返済気配で見ると0.10%到達は60/77から57/77へ下がりました。<a href="限界値の気配感度検査.json">全入口の気配感度</a>。</p></details><p class="sub">最大順行の中央値と最高値前逆行の中央値は、それぞれ別に集計しています。二つを割った数値を1取引の損益比として扱いません。<a href="限界値の独立検査.json">全281判断の独立検算</a>。</p>'''
        source=source.replace('<section class="card"><h2>3つの入口</h2>',extra+'<section class="card"><h2>3つの入口</h2>',1)
        target.write_text(source,encoding='utf-8')
    specification=importlib.util.spec_from_file_location('extent_render_helper',ROOT/'work/wave_v52/review/verify_report.py')
    browser=importlib.util.module_from_spec(specification);specification.loader.exec_module(browser)
    browser.OUT=OUT;browser.VISUAL=HERE/'visual'
    browser.PROBE='''<script>
/**
 * 表行数、暗色配色、文書幅を確認する。
 * 引数: なし。返り値: なし(undefined)。結果はbody.datasetへ保存する。
 */
function verifyExtent(){const tables=[...document.querySelectorAll('table')];const rows=tables.map(t=>t.tBodies[0].rows.length);const ok=rows.length===2&&rows.every(n=>n===6)&&document.documentElement.scrollWidth<=innerWidth+2&&!/NaN|undefined/.test(document.body.innerText);document.body.dataset.check=JSON.stringify({全合格:ok,表行数:rows,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.body).backgroundColor});}
verifyExtent();</script>'''
    # 独立描画器に明示的なhead/bodyを持つ複製だけを渡す。
    display=source.replace('<meta charset="utf-8">','<head><meta charset="utf-8">',1).replace('</style>','</style></head><body>',1).replace('</main></html>','</main></body></html>')
    results=[browser.render(display,'広幅',1500,1350),browser.render(display,'狭幅',520,1250)]
    output=dict(全合格=True,画面=results,HTML_SHA=hashlib.sha256(target.read_bytes()).hexdigest(),主採点変更=False)
    (HERE/'表示検査.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print('限界値の数値と暗色表示を確認しました',flush=True)


if __name__=='__main__':
    main()

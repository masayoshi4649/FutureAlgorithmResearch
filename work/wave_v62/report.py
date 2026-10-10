"""銘柄専用の黒字候補について、偶然性診断の意味と限界を短く整理する。"""

import html
import json
from pathlib import Path
import re


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
FOLDER='00059_銘柄別黒字候補の偶然性確認'
OUT=ROOT/'アルゴリズム調査'/FOLDER
TITLE='片方だけの黒字は偶然ではないと言えるか'


def amount(value: float) -> str:
    """機能: 円損益を符号付きの読みやすい表記へ変換する。

    引数: value(float)。返り値: 表示文字列(str)。
    """
    return f'{value:+,.0f}円'.replace('-','−')


def main() -> None:
    """機能: 固定結果を短い暗色HTMLへまとめ、調査一覧に追加する。

    引数: なし。返り値: なし(None)。過去の作業フォルダは編集しない。
    """
    OUT.mkdir(parents=True,exist_ok=True)
    result=json.loads((HERE/'偶然性の診断.json').read_text(encoding='utf-8'))
    candidates=sorted(result['候補'],key=lambda x:x['銘柄']!='TOPIX')
    reference=next(x for x in result['再標本化'] if x['対象']=='12日・24場' and x['平均ブロック日数']==2)
    rows=''
    for c in candidates:
        p=next(x for x in reference['候補'] if x['候補列']==c['列'])
        ci=p['平均日収支の基本法95区間']
        rows+=f'''<tr><td>{html.escape(c['銘柄'])}<br><small>{html.escape(c['条件ID'])}</small></td><td>{amount(c['集計']['net'])}</td><td>{amount(c['集計']['without_best'])}</td><td>{amount(c['最大黒字日除外'])}</td><td>{amount(ci[0])} ～ {amount(ci[1])}</td><td>{p['単独片側参考p']:.2f}</td></tr>'''
    details=''
    for r in result['再標本化']:
        for p in r['候補']:
            c=next(x for x in candidates if x['列']==p['候補列'])
            lo,hi=p['平均日収支の基本法95区間']
            details+=f'<tr><td>{r["対象"]}</td><td>{r["平均ブロック日数"]}</td><td>{c["銘柄"]}</td><td>{amount(lo)} ～ {amount(hi)}</td><td>{p["単独片側参考p"]:.3f}</td><td>{p["全900系列最大値調整参考p"]:.3f}</td></tr>'
    page=f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{TITLE}</title><style>
body{{background:#101720;color:#e3eaf3;font:16px/1.75 system-ui,sans-serif;margin:0}}main{{max-width:1160px;margin:auto;padding:24px}}a{{color:#93c8ff}}h1{{font-size:1.6rem}}h2{{font-size:1.15rem;margin-top:24px}}.notice{{background:#182432;border-left:4px solid #8abcff;padding:15px}}.wrap{{overflow-x:auto;margin:15px 0;border:1px solid #35485e}}table{{border-collapse:collapse;width:100%;white-space:nowrap;font-size:.88rem}}th,td{{padding:9px;text-align:right;border-bottom:1px solid #35485e}}th{{background:#25374c}}td:first-child,th:first-child{{text-align:left}}small,.muted{{color:#adc0d3}}summary{{cursor:pointer;color:#b0d1ff}}@media(max-width:600px){{main{{padding:12px}}h1{{font-size:1.3rem}}}}
</style></head><body>
<!--
[コンポーネント概要]
main は銘柄別黒字候補の偶然性を確認した短い報告です。
.notice は結論、.wrap は比較表の内部横スクロール領域です。
details は仮定付き統計診断の仕様と全感度結果を開閉します。
--><main><nav><a href="../index.html">調査一覧</a> · <a href="README.md">資料案内</a></nav><h1>{TITLE}</h1>
<div class="notice"><strong>現時点では言えません。今回の2候補は「偶然を排除できていない黒字候補」です。</strong><p>片方の銘柄だけに有効な手法はあり得ます。しかし、片方で黒字だった結果だけでは、銘柄固有の性質に効いたのか、探索中の偶然なのかを区別できません。</p></div>
<p>00058の売買条件・約定結果は変更せず、手数料後の25場を追加診断しました。TOPIX mini最大10枚・NK225 micro最大20枚の枠内です。新しい売買条件の探索、現在APIの追加取得は行っていません。</p>
<div class="wrap"><table><thead><tr><th>対象</th><th>全25場</th><th>最大黒字場除外</th><th>最大黒字日除外</th><th>完全12日の平均日収支・参考95%区間</th><th>単独の参考p値</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="muted">「日」は同じ日付ラベルのデイ＋ナイト。全25場は12日分と10/7デイのみです。収支・除外額は全25場、参考区間とp値は比較単位を揃えた完全12日を使用。平均2日ブロック・2万回の再抽出による、選択未補正の基本法区間です。この少数標本による区間を精密な確率評価とは扱いません。</p>
<h2>今回の黒字を強い根拠にできない理由</h2>
<ol><li><strong>利益に対して変動が大きい。</strong>候補を最初から1つだけ決めていたと仮定した補助診断でも、両方の平均日収支の区間が赤字と黒字をまたぎます。参考p値も0.32・0.37で、通常の5%水準を満たしません。</li>
<li><strong>好成績を後から選んでいる。</strong>450条件×2銘柄の900系列を同時に見た選択を考慮した参考診断でも、優位性の裏付けは得られません。過去のさらに多くの探索まで補正できているわけではありません。</li>
<li><strong>特定の日と設定への依存がある。</strong>最大黒字日を除くと両方赤字です。TOPIXは上限30分で黒字でも15分・60分では赤字でした。これは集中度の点検であり、大勝ちを伴う戦略を一律に否定する試験ではありません。</li></ol>
<h2>片方専用の手法を認めるには</h2>
<p>両銘柄で黒字になることは必須条件ではありません。必要なのは、<strong>銘柄を選ぶ理由・入口・保有管理・出口を先に固定し、その銘柄の未参照データでも費用後の優位性が再現すること</strong>です。値動きの戻り方、気配差、変動幅などの違いに理由を置き、その条件が成立した場で効くかを確かめます。</p>
<p>今回の2候補には、その確認がまだありません。00058で現在確認したのは別の固定参考条件であり、この2候補の未知成績の代わりにはしません。今後の評価期間・判定基準を先に決め、結果を見て条件を変更した場合は新候補として扱う必要があります。</p>
<p><strong>結論は「偶然だったと証明した」でもありません。利益の源泉を示して採用できるほどの証拠が、現状は不足しています。</strong></p>
<details><summary>統計診断の仕様・全感度結果・限界</summary>
<p>日別の費用後収支を900列へ並べ、全列に同じ再抽出日を適用します。連続する日を幾何分布の長さで再利用し、列間の関連を保ちます。各列を自身の平均で中心化し、原標本の標準偏差で尺度を揃えた平均と、900列の最大値を比較します。全900系列の期待収支をゼロに置く保守的な基準による、片側・最大値の仮定付き再標本化診断です。標準t検定やWhite検定の完全実装とは呼びません。</p>
<p>計算前に固定した平均ブロック長1・2・4日、完全12日と全13日の6通りを省略せず掲載します。すべて同じく優位性を裏付けません。定常性・弱い依存などを仮定し、短期資料の相場変化を証明で消せません。4日ブロックでは実質的な塊も約3つしかありません。取引や枚数を独立標本として水増ししていません。p値は『偶然である確率』ではなく、仮定した基準の下で同等以上の統計量が出る参考頻度です。</p>
<div class="wrap"><table><thead><tr><th>資料</th><th>平均ブロック日数</th><th>銘柄</th><th>平均日収支の参考95%区間</th><th>単独参考p</th><th>900系列最大値参考p</th></tr></thead><tbody>{details}</tbody></table></div>
<p>多条件の探索による偶然性を考慮する理由は<a href="https://doi.org/10.1111/1468-0262.00152">WhiteのData Snooping研究</a>、連続性を残す再抽出は<a href="https://www.tandfonline.com/doi/abs/10.1080/01621459.1994.10476870">Politis–RomanoのStationary Bootstrap</a>を参照。論文の一般理論が、この短期資料の利益や検定精度を保証するものではありません。</p>
<nav><a href="../../work/wave_v62/診断仕様.json">仕様</a> · <a href="../../work/wave_v62/偶然性の診断.json">計算結果</a> · <a href="../../work/wave_v62/review/README.md">独立確認</a></nav></details></main></body></html>'''
    (OUT/f'{TITLE}.html').write_text(page,encoding='utf-8')
    (OUT/'README.md').write_text(f'''# 銘柄別黒字候補の偶然性確認

最初に [{TITLE}]({TITLE}.html) を開いてください。

読む順序：

1. 上記HTMLの結論と比較表。
2. 同じHTMLの「片方専用の手法を認めるには」。
3. 折りたたみ内の統計診断仕様と全感度結果。
4. [診断仕様](../../work/wave_v62/診断仕様.json)、[全結果](../../work/wave_v62/偶然性の診断.json)、[独立確認](../../work/wave_v62/review/README.md)。

元の売買結果は00058の固定済み450条件です。売買の再探索・現在API取得はありません。コードは `work/wave_v62/check_chance.py`、日別行列は `work/wave_v62/日別損益行列.npz`。過去の報告書は上書きしていません。

すべて既知資料で、統計診断の設計自体も事後です。偶然でない証明、独立した未知検証、実際の小型商品での約定保証とは呼びません。収支はラージ気配を代理にした費用後です。

表示の再生成は `python -X utf8 work/wave_v62/report.py`。売買・APIアクセスは発生しません。診断計算は仕様とコードSHAを固定しており、再実行による上書きは停止します。
''',encoding='utf-8')
    # ----------------------------------------
    # 一覧に今回の入口を加え、以前の作業リンクを残す。
    path=ROOT/'アルゴリズム調査'/'README.md'
    text=path.read_text(encoding='utf-8')
    text=re.sub(r'<!--00059案内開始-->.*?<!--00059案内終了-->\s*','',text,flags=re.S)
    text=text.replace('**最新は00058の','**00058の')
    header='# アルゴリズム調査の作業一覧\n\n'
    assert text.startswith(header)
    notice=f'<!--00059案内開始-->\n**最新は00059の[{TITLE}]({FOLDER}/{TITLE}.html)。銘柄別首位2候補の利益集中と、900系列の選択を含む仮定付き偶然性診断。**\n<!--00059案内終了-->\n\n'
    path.write_text(header+notice+text[len(header):],encoding='utf-8')
    path=ROOT/'アルゴリズム調査'/'index.html'
    text=path.read_text(encoding='utf-8')
    text=re.sub(r'<!--00059開始-->.*?<!--00059終了-->','',text,flags=re.S)
    text=text.replace('class="task latest"','class="task"').replace('<span class="badge">最新</span>','')
    text=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00059：片方だけの黒字は偶然ではないと言えるか。利益集中と多条件選択を追加確認。</p>',text,count=1,flags=re.S)
    block=f'<!--00059開始--><article class="task latest"><div class="number">作業00059 <span class="badge">最新</span></div><h2>銘柄別黒字候補の偶然性確認</h2><p>同じ売買結果から、日単位の利益集中と仮定付き統計診断。銘柄専用の手法を認める条件も簡潔に整理。</p><a class="button" href="{FOLDER}/{TITLE}.html">説明と診断結果 →</a></article><!--00059終了-->'
    assert '<!--00058開始-->' in text
    path.write_text(text.replace('<!--00058開始-->',block+'\n<!--00058開始-->',1),encoding='utf-8')
    print(str(OUT/f'{TITLE}.html'))


if __name__=='__main__':
    main()

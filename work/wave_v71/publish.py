"""入口確認と幅拡大の結果・資料案内を保存し、新作業を一覧へ登録する。"""

import hashlib
from pathlib import Path
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

import report
import study

HERE=Path(__file__).resolve().parent
INDEX=report.ROOT/'アルゴリズム調査/index.html'
README=INDEX.parent/'README.md'


def yen(value: float) -> str:
    """機能: 収支を符号付き円表記へ変換する。

    引数: value(float)。返り値: 日本語金額(str)。
    """
    return f'{value:+,.0f}円'


def documents() -> None:
    """機能: 保存会計から短い結論と資料の読む順を作る。

    引数: なし。返り値: なし(None)。
    """
    selected=study.load(HERE/'前半選定.json')
    lines=[]
    choices=[dict(id=selected['基準'],label='従来')]+selected['代表']
    for choice in choices:
        r=study.load(HERE/'results'/(choice['id']+'.json'))
        top,nk=[r['periods']['全28'][s] for s in study.SYMBOLS]
        et,en=[r['periods']['追加1'][s] for s in study.SYMBOLS]
        lines.append(f"| {choice['label']} | {yen(top['net'])} | {yen(nk['net'])} | {top['campaigns']}／{nk['campaigns']} | {yen(et['net'])} | {yen(en['net'])} |")
    result='''# 入口確認とトレーリング幅拡大の結果

**最初に見るファイル：[入口確認と幅拡大の説明と損益](入口確認と幅拡大の説明と損益.html)。** 各章で銘柄・期間を切り替えると、入口だけ／幅だけ／両方の損益、全29場と週の利益・損失・枚数、方向先着率、五分足と売買を確認できます。

入口を厳しくする案と、追跡幅を広げる案を分けて試した。6入口×4確認×6幅×3管理＝432条件。主比較の結論は、**損失総額は減ったが、入口の近い方向先着率は改善せず、両銘柄で安定黒字にするには届かなかった**。一方、少数の表示補充反転では幅拡大によって黒字・損小利大になる例があったため、別枠に掲載する。

## 同じ入口部品での切分け

前16だけで選んだ共通比較例はT2L0_G2_W2_H。両銘柄20組・8活動場以上の最低数は満たすが、前半黒字・損小利大という採用条件は未達。3章はこの1例の入口／幅の対照で、独立した3有望手法を選んだものではない。

| 変更 | 全28 TOPIX | 全28 日経 | 組数TOP／NK | 追加10/09 TOPIX | 追加10/09 日経 |
| --- | ---: | ---: | ---: | ---: | ---: |
'''+ '\n'.join(lines)+'''

G2は、候補方向に直近4中値イベントの買い・売り両気配が各1呼値以上前進し、16中値イベントの純進行2呼値以上、直進性0.30以上、最良OFI方向比0.10以上を要求する。履歴120秒以内・品質連続。W2は**元玉の幅8呼値を維持し、保険の幅4→8呼値だけを広げる**。元玉だけ2倍、両方2倍／3倍、開始条件も2倍を含む全6幅を同じ入口で表示している。

元玉stop32、全玉損失枠32呼値相当、逆行8呼値ごとの保険約25%、最長60分、初回満額、片方向TOPIXミニ10枚／日経マイクロ20枚は全設定で固定。幅による早期返済で次入口数が増えないよう初回から3630秒は次親予約を待つ。

## 入口は本当に確度が上がったか

実新規買ask／売bidから、将来の返済気配が順行8／16呼値と逆行8／16呼値のどちらへ先に届いたかを採点した。60分の出口と独立に場内返済期限まで見る。未到達は勝ちにしない。未来価格は採点専用で、入口を選ぶ時には使用しない。

T2全28、G0→G2：

- ±8先着：TOP85/191＝44.5%→24/57＝42.1%、NK84/222＝37.8%→11/51＝21.6%。
- ±16先着：TOP45.0%→43.9%、NK39.2%→43.1%。
- 場末までの最大順行の中央値はTOP24→31呼値、NK21.5→36呼値。

後で大きく進んだことと、その前に逆行しないことは違う。直前の気配・板フローの一致を増やしても、この定義では近い方向確度の改善にならなかった。組数がTOP191→57、NK222→51まで減り総損失も減ったが、1組平均収支はTOP−1.02→−1.47呼値、NK−2.74→−3.16呼値で悪化した。**総損失の減少だけを入口精度の向上とは呼ばない。**

幅の効果も一律ではない。G2で保険幅だけ4→8にすると全28 TOPは+67,496円改善、NKは−8,050円悪化。確認G0のまま同じ変更ではTOP−102,513円悪化、NK+170,790円改善。元方向に回復した時に残る保険を切る問題は、幅拡大だけでは解消していない。

## 少数だが黒字だった幅拡大例

**T3L1_G1_W4_D：表示回復後の反転、保険なし、元玉追跡幅8→24呼値（TOP4→12pt／NK80→240円）。** 開始8、元stop32、最長60分。G1とG0の入口は同一なので、入口確認の成功とは呼ばず幅の参考として扱う。全結果を見た事後の例で主選定ではない。

| 商品 | 従来の全28収支 | 拡大後の全28収支 | 組数 | 平均勝組／負組 | 前16収支 | 最大黒字場を除く |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| TOPIXミニ10枚 | +234,068円 | +184,068円 | 37 | 1.68 | +231,608円 | −74,260円 |
| 日経マイクロ20枚 | +1,840円 | +113,840円 | 14 | 1.23 | −38,640円 | +10,280円 |

TOPの利益は5万円減ったが、平均勝ち／負け比が1を超えた。日経は収支・同率が改善した。ただし前半の日経は6組で件数不足かつ赤字、TOP後12は−47,540円、最大黒字場への依存も残る。追加10/09はTOP+14,164円／日経0組であり、無取引を勝ちとはしない。**試す価値のある参考例だが、安定性の結論はまだ出せない。**

## 検証の範囲

前28（09/21デイ〜10/08ナイト）は既知。前16でのみ選定し、後12・追加10/09で選び直さない。全29は保存データの単純合計。G1/G2は自市場の原本seq順で因果検査済み。G3は1秒以上前の相手の約定時計・同秒先頭・古さ5秒以内を使う同期参考で、共通受信時計がないため実時間の受信順を証明できず主選定から外した。

ラージの買ask／売bidで判断した次の有効原本行に仮想約定し、小商品の手数料（片道1枚TOPIXmini41.8円／NK225micro11円）を注文合計で切捨て。利益・損失へ新規／返済両側の料金を含む。全玉・全原本行の含み損益、FIFO、部分料金、最大保有を記録。実小商品の板・深さ・通信・取消競合は未再現。

25,056口座の独立会計・4,320期間集計・入口の根拠と未来切断・改変・15固定SHA・9,966方向先着を照合。旧管理エンジンは変更していない。API取得0、実注文0。旧成果、App/E01、原本は変更していない。保険玉の独立損切りや元方向再開による保険削減は、今回の入口／幅比較には加えていない。

全条件は[全432条件の比較](全432条件の比較.html)、再現と監査は[資料案内](README.md)。
'''
    (report.OUT/'検証結果.md').write_text(result,encoding='utf8')
    guide='''# 作業00068：入口確認とトレーリング幅拡大

**最初に見るファイル：[入口確認と幅拡大の説明と損益](入口確認と幅拡大の説明と損益.html)。** 入口のみ・幅のみ・同時変更の3比較、少数黒字参考、全場／週損益・枚数、方向先着率、五分足売買図。

読む順序：

1. [主HTML](入口確認と幅拡大の説明と損益.html)：短い説明と対照、全29場・週会計。
2. [全432条件の比較](全432条件の比較.html)：全条件と前16／後12／追加デイの分離会計。
3. [短い検証結果](検証結果.md)：入口確度、幅単独の効果、少数黒字例の限界。
4. [事前固定](../../work/wave_v71/事前固定.json)・[前半選定](../../work/wave_v71/前半選定.json)・[事前仮説](../../work/wave_v71/theory/入口確認と幅拡大の事前仮説.md)。
5. [監査の読む順](../../work/wave_v71/audit/README.md)・[公開説明と会計の監査](../../work/wave_v71/audit/公開説明と会計の最終監査.json)・[全HTML表示検査](../../work/wave_v71/review/HTML表示の独立検査.json)。

## 実装と証跡

- [入口確認の読む順](../../work/wave_v71/inputs/README.md)・[確認仕様](../../work/wave_v71/inputs/入口確認の事前固定.json)・[確認エンジン](../../work/wave_v71/inputs/core.py)。
- [比較と会計](../../work/wave_v71/study.py)・[選定](../../work/wave_v71/select.py)。管理は[旧00067エンジン](../../work/wave_v70/engine.py)と[縮小復帰写像](../../work/wave_v70/net.py)を変更せず使用。
- [入口の方向診断](../../work/wave_v71/analysis/入口方向の独立診断.json)・[追加デイ入力](../../work/wave_v71/prepared/追加デイの入力照合.json)。
- [レポート生成](../../work/wave_v71/report.py)・[表示検査](../../work/wave_v71/verify.py)。

成果と台帳はwork/wave_v71/resultsとledgersへ保存。既知28場はwave_v69/preparedとwave_v70/inputsを読取り再利用、追加10/09デイはwave_v71/preparedへ独立抽出。book・candle_1min・candle_5minは読取専用、現在API取得0、実注文0。実注文アプリの変更ではなく研究用の保存板再生。

## 再現

プロジェクトルートから（Python・numpy・numba・pandas、表示検査にはBeautifulSoupとChrome）：

```text
python -X utf8 work/wave_v71/study.py
python -X utf8 work/wave_v71/select.py
python -X utf8 work/wave_v71/report.py
python -X utf8 work/wave_v71/verify.py
```

study.pyは既存結果を再利用する。--sourceで6入口の一つを指定して分割できる。既存の入口や固定を再作成しないため--freeze、inputs/prepare.py、prepare_extra.pyは再現時に実行しない。新条件や追加場の研究は別作業へ分け、今回の前半順位は後半損益で変えない。

verify.pyは目視欄を未確認へ戻す。生成画像を見た後に目視確認を記録する。未知期間の収益性や実商品約定を保証する検査ではない。
'''
    (report.OUT/'README.md').write_text(guide,encoding='utf8')


def main() -> None:
    """機能: 会計・公開SHA・目視を確認し、最新00068と全資料リンクを登録する。

    引数: なし。返り値: なし(None)。
    """
    proof=study.load(HERE/'review/HTML表示の独立検査.json')
    audit=study.load(HERE/'audit/公開説明と会計の最終監査.json')
    assert proof['全合格'] and proof['目視確認'] and audit['合格']
    assert study.load(HERE/'audit/全条件の独立監査.json')['合格']
    for filename,key in ((report.MAIN,'主HTML_SHA256'),(report.ALL,'全条件HTML_SHA256')):
        assert hashlib.sha256((report.OUT/filename).read_bytes()).hexdigest()==proof[key]==audit[key]
    fixed=study.load(HERE/'事前固定.json')
    assert all(hashlib.sha256((report.ROOT/path).read_bytes()).hexdigest()==digest for path,digest in fixed['SHA256'].items())
    documents()
    folder=report.OUT.name
    source=INDEX.read_text(encoding='utf8').replace('class="task latest"','class="task"').replace(' <span class="badge">最新</span>','')
    source=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00068：入口確認と元玉・保険の追跡幅を432条件で比較。既知28場と追加10/09デイを分離し、方向先着率と損益を掲載。</p>',source,count=1)
    block=f'''<!--00068開始--><article class="task latest"><div class="number">作業00068 <span class="badge">最新</span></div><h2>入口確認とトレーリング幅拡大</h2><p>入口だけ・幅だけ・同時変更を切り分ける432条件。TOPIXミニ10枚／日経マイクロ20枚、保存29場。全場／週損益・枚数、方向先着率、5分足売買図。少数黒字参考と採用判断を区別。</p><a class="button" href="{folder}/{report.MAIN}">入口確認と幅拡大の結果を開く →</a><p><a href="{folder}/{report.ALL}">全432条件</a> · <a href="{folder}/検証結果.md">短い検証結果</a> · <a href="{folder}/README.md">資料案内</a></p></article><!--00068終了-->'''
    if '<!--00068開始-->' in source:
        source=re.sub(r'<!--00068開始-->.*?<!--00068終了-->',block,source,flags=re.S)
    else:
        assert '<!--00067開始-->' in source
        source=source.replace('<!--00067開始-->',block+'\n<!--00067開始-->',1)
    INDEX.write_text(source,encoding='utf8')
    text=README.read_text(encoding='utf8').replace('**最新は00067','**00067')
    guide=f'''<!--00068案内開始-->
**最新は00068の[入口確認と幅拡大の説明と損益]({folder}/{report.MAIN})。432条件、保存28場と追加10/09デイの分離会計。入口だけ／幅だけ／両方の対照、全場と週の損益・枚数、方向先着率、五分足売買図。**

[全432条件]({folder}/{report.ALL}) · [短い検証結果]({folder}/検証結果.md) · [資料案内]({folder}/README.md)。
<!--00068案内終了-->
'''
    if '<!--00068案内開始-->' in text:
        text=re.sub(r'<!--00068案内開始-->.*?<!--00068案内終了-->\n?',guide,text,flags=re.S)
    else:
        assert '<!--00067案内開始-->' in text
        text=text.replace('<!--00067案内開始-->',guide+'\n<!--00067案内開始-->',1)
    README.write_text(text,encoding='utf8')
    # ----------------------------------------
    # 新しい資料案内と新旧一覧の相対リンクを照合する。
    count=0
    for path in (INDEX,report.OUT/report.MAIN,report.OUT/report.ALL):
        for tag in BeautifulSoup(path.read_text(encoding='utf8'),'html.parser').select('a[href]'):
            href=tag['href']
            if href.startswith(('http','#')):continue
            assert (path.parent/unquote(href.split('?',1)[0].split('#',1)[0])).resolve().exists(),href
            count+=1
    for path in (README,report.OUT/'README.md',report.OUT/'検証結果.md'):
        for href in re.findall(r'\]\(([^)]+)\)',path.read_text(encoding='utf8')):
            if href.startswith(('http','#')):continue
            assert (path.parent/unquote(href.split('?',1)[0].split('#',1)[0])).resolve().exists(),href
            count+=1
    study.save(HERE/'公開リンク照合.json',dict(全合格=True,最新作業='00068',リンク数=count,固定SHA不変=True,API取得=0,実注文=0))
    print('00068を最新へ登録、リンク確認:',count)


if __name__=='__main__':
    main()

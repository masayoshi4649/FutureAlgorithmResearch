"""新しい作業の案内を追加し、過去の公開レポートを変更せずリンクを検証する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
FOLDER='00075_J2赤字上位セッションの板検証と防止策'
MAIN='赤字上位3セッションの板と防止策.html'
OUT=ROOT/'アルゴリズム調査'/FOLDER


def documents() -> None:
    """機能: 主要資料の読む順序と、検証結果・再現条件を記載する。

    引数: なし。返り値: なし(None)。
    """
    text=f'''# 作業00075：J2赤字上位セッションの板検証と防止策

最初に見るファイルは **[{MAIN}]({MAIN})** です。

読む順序：

1. 主HTML：赤字上位3場ずつ、全18取引の具体的な板・新規・返済時刻。入口で既知だった根拠と、判断後の反転を分離。
2. 同じHTMLの「防ぐにはどうすればよいか」：入口6×出口3の全18条件。赤字だけを省くのでなく、全30場を注文から再生。全場の利益・損失・収支も手法切替で表示。
3. [公開会計](公開会計.json)、[損益計算前の固定条件](../../work/wave_v79/事前固定.json)、[利益減少と損失削減](../../work/wave_v79/analysis/全条件の効果.json)。
4. 板の詳しい根拠：[TOPIX](../../work/wave_v79/topix/TOPIX上位3赤字場の診断.json)、[日経](../../work/wave_v79/nk225/赤字三場の全組と入口根拠.json)、[同じ新規の実再生時刻](../../work/wave_v79/analysis/赤字上位6口座の再生時刻.json)。
5. [独立会計監査](../../work/wave_v79/audit/全18防止策と3遅延の独立会計監査.json)、[未来不変の検査](../../work/wave_v79/audit/全18防止策の実注文未来不変監査.json)、[結論の敵対レビュー](../../work/wave_v79/report/結論レビュー.json)。

## 結論

**損失の中心は価格の逆行です。両市場の過去の同方向進行は観測できていましたが、その後の継続需要を保証しません。** 基準J2は、当場始値0.4%の幅と30分の期限まで保有するため、小さな順行の後に反転した場合は損失が大きくなりました。

TOPIXの赤字上位3場は−496,688円。このうち中値差−430,000円、気配差負担60,000円、手数料6,688円。日経は−284,400円、中値差−253,000円、気配差27,000円、手数料4,400円です。TOPIXの7敗中5敗、日経の9敗中6敗は両15秒OFIが支持しても負けました。

**入口を従来どおりにした早期撤退E0_X1は最悪場を改善しますが、全体を赤字へ変えました。採用しません。** 以下のX1列はE0_X1です。

| 手数料後 | TOPIX基準 | TOPIX X1 | 日経基準 | 日経 X1 |
| --- | ---: | ---: | ---: | ---: |
| 自商品の赤字上位3場 | −496,688 | −217,524 | −284,400 | −114,840 |
| 残り27場 | +1,229,808 | +60,596 | +772,040 | −41,920 |
| 全30場総利益 | 2,566,544 | 1,368,232 | 1,087,960 | 456,560 |
| 全30場総損失 | 1,833,424 | 1,525,160 | 600,320 | 613,320 |
| 全30場収支 | +733,120 | −156,928 | +487,640 | −156,760 |

入口のOFI積極支持必須・距離加重板の反対排除も、情報遅延1/5/15秒すべてで両商品の基準収支を下回りました。根拠気配から1呼値超の追いかけを避ける案は、5秒では両方悪化し、他の遅延では効果の符号が変わります。全面採用できる改善は未発見です。全ての板読みや全てのトレール幅が無効だと示したものではありません。

## 具体例

- 10/5 TOPIX：08:54:24の買4135.5×2／売4136×5を参照。両指数の下落と売りOFIがあり、08:54:30に売り判断。判断時の買気配は4134へ3呼値下がり、追いかけもあった。新規4134.5、09:19:27に4148.5返済で−140,836円。X1なら08:55:33に4137.5返済、−30,836円。ただし他の場の勝ちも切る。
- 9/29ナイトの日経：23:46買いは相手TOPIXの15秒中値が同値、両15秒OFIも弱かった。23:46:42のX1返済なら−6,440円、基準は翌00:04:58に−40,440円。弱い入口だけでなく、翌00:27の両OFIが明確な売りも−54,440円負けている。
- 10/9 日経：09:41買いではOFIは買い支持だが、参照板の買/売数量はTOPIX3/18、日経1/14。短い累積フローと残っている板は矛盾。ただし、この板厚で一律見送る案も全体改善にならなかった。

## 検証条件

- 基準はJ2_F0_B0_H0_R0（E0_X0）。両市場の300秒中値が同方向へ各3bp以上、自市場15秒の売買両気配が各1呼値同方向、相手短期が逆でない。明確な逆OFIを除き、弱い側の300秒進行が強い側の25%以上。
- 基準の出口は当場始値0.4%幅を呼値へ切上げ、最低2呼値、30分期限又は場内撤収。TOPIXミニ10枚／日経マイクロ20枚、全量初回、追加・両建てなし。
- 入口6・出口3を新損益前に固定。全30場、商品別最悪3/残27、両商品診断対象5場を除く25、前16/後14を評価。主情報遅延5秒と1/15秒感度を全18案で比較。前後区分は未知の標本を意味しない。
- 新規後の逆行確認で返済するX1/X2はトレーリング幅自体を変えない。欠測を反対方向として扱わず、双方の価格窓と参照更新を要する。
- 原本CurrentPriceTimeを代理時計とした厳密過去・同時計先頭参照。真の受信時計の順序は証明できない。入口の旧15秒格子とJ2追加5秒格子を混同しない。
- 判断後次有効原本のラージ気配で仮想約定。買ask・売bid、TOPIX片道41.8円／日経11円、注文合計の円未満切捨て。ミニ/マイクロ固有の板・待ち順位・市場影響は未再現。
- 全玉場内返済、未決済玉の損失隠しなし。新方式の損益は保有状態と再エントリーを含めた完全再生で、元取引の事後除外ではない。
- 含み益の頂点、後の安値・高値、未来の方向は事後診断だけに使用。赤字日を見てから作った対策であり、全30場も既知資料。未来の改善の証明ではない。
- 現在API取得0、実注文0。生データ・00074等の旧公開レポートは変更していない。

## 再現

```text
python -X utf8 work/wave_v79/experiment.py --workers 4
python -X utf8 work/wave_v79/experiment.py --delay 1 --workers 3
python -X utf8 work/wave_v79/experiment.py --delay 15 --workers 3
python -X utf8 work/wave_v79/analyse.py
python -X utf8 work/wave_v79/report/case_data.py
python -X utf8 work/wave_v79/report/generate.py
```

固定済みの条件は上書き不可。保存済み結果は再生を省略するため、ゼロから再計算する場合は別出力先を用意してください。
'''
    (OUT/'README.md').write_text(text,encoding='utf8')


def indexes() -> None:
    """機能: 作業一覧とルートの最新案内だけを新作業へ更新する。

    引数: なし。返り値: なし(None)。既存の本文は残す。
    """
    index=ROOT/'アルゴリズム調査/index.html';html=index.read_text(encoding='utf8')
    if '<!--00075開始-->' not in html:
        html=html.replace('class="task latest"','class="task"')
        marker=html.index('<!--00074開始-->')
        addition=f'''<!--00075開始--><article class="task latest"><div class="number">作業00075 <span class="badge">最新</span></div><h2>J2赤字上位の板検証と防止策</h2><p>両商品の赤字上位3場・全18取引を原板へ照合。入口の根拠と反転後を分け、18防止策を全30場・3遅延で再生。大損の削減と勝ちの喪失を比較。</p><a class="button" href="{FOLDER}/{MAIN}">板・注文時刻と防止策を開く →</a><p><a href="{FOLDER}/README.md">資料案内</a> · <a href="{FOLDER}/公開会計.json">公開会計</a></p></article><!--00075終了-->\n'''
        html=html[:marker]+addition+html[marker:]
        html=html.replace('作業00074 <span class="badge">最新</span>','作業00074')
        index.write_text(html,encoding='utf8')
    path=ROOT/'アルゴリズム調査/README.md';text=path.read_text(encoding='utf8')
    if '<!--00075案内開始-->' not in text:
        text=text.replace('**最新は00074の','**00074の')
        text=text.replace('# アルゴリズム調査の作業一覧\n',f'''# アルゴリズム調査の作業一覧

<!--00075案内開始-->
**最新は00075の[{MAIN}]({FOLDER}/{MAIN})。赤字上位3場ずつの全18取引を具体的な板・時刻で診断。18防止策は局所改善と全体悪化を分けて掲載。**

[読む順序]({FOLDER}/README.md) · [公開会計]({FOLDER}/公開会計.json)。
<!--00075案内終了-->
''',1)
        path.write_text(text,encoding='utf8')
    path=ROOT/'README.md';text=path.read_text(encoding='utf8')
    text=re.sub(r'^最新の調査は .*$',f'最新の調査は **[00075：J2赤字上位の板検証と防止策](アルゴリズム調査/{FOLDER}/{MAIN})** です。[資料案内と読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。赤字上位3場ずつを原板へ照合し、18防止策を全30場で再生しました。',text,count=1,flags=re.MULTILINE)
    path.write_text(text,encoding='utf8')


def verify() -> None:
    """機能: 公開リンクと過去レポートの不変性を検査する。

    引数: なし。返り値: なし(None)。
    """
    count=0
    for path in (OUT/MAIN,OUT/'README.md',ROOT/'README.md',ROOT/'アルゴリズム調査/index.html',ROOT/'アルゴリズム調査/README.md'):
        text=path.read_text(encoding='utf8')
        refs=[a['href'] for a in BeautifulSoup(text,'html.parser').select('a[href]')] if path.suffix=='.html' else re.findall(r'\]\(([^)]+)\)',text)
        for href in refs:
            if href.startswith(('http:','https:','#')):continue
            assert (path.parent/unquote(href.split('#')[0].split('?')[0])).exists(),(path,href)
            count+=1
    old=ROOT/'アルゴリズム調査/00074_歴代手法の再評価と二市場統合'
    hashes={'過去の知見を統合した手法と全セッション損益.html':'79086d792f9e9aef423eb56fa5b54e04f8a656dd36a2024a16fc4773d6920b13','全162条件の比較.html':'5ef43354ca9399cc833aa3a54d601d0ffc90d421323b3f2831994cdb65bd5435'}
    for name,expected in hashes.items():assert hashlib.sha256((old/name).read_bytes()).hexdigest()==expected,name
    proof=dict(合格=True,リンク数=count,旧00074不変更=hashes,HTML_SHA256=hashlib.sha256((OUT/MAIN).read_bytes()).hexdigest())
    (HERE/'report/案内と旧成果不変更の確認.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    documents();indexes();verify()

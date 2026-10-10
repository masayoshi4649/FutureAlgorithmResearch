"""作業00066の結果と読む順を保存し、既存一覧へ新作業を登録する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

import report

HERE = Path(__file__).resolve().parent
INDEX = report.ROOT/'アルゴリズム調査/index.html'
README = INDEX.parent/'README.md'


def yen(value: float, signed: bool = False) -> str:
    """機能: 整数会計の円表示を作る。

    引数: value(float)、signed(bool)。返り値: 日本語の金額(str)。
    """
    return f'{value:+,.0f}円' if signed else f'{value:,.0f}円'


def documents(selection: dict) -> None:
    """機能: 条件別の損益を直接保存集計から読み、短い結果と資料案内を書く。

    引数: selection(dict)。返り値: なし(None)。
    """
    family = {1:'中値往復の反転',2:'押し戻し後の再開',3:'表示補充後の反転',4:'表示補充価格の突破'}
    products = {'TOPIX':'TOPIXミニ5枚','NK225':'日経マイクロ10枚'}
    lines = []
    for selected in selection['選定']:
        result = report.load(HERE/'results'/(selected['id']+'.json'))
        for symbol in ('TOPIX','NK225'):
            a = result['periods']['全28'][symbol]
            lines.append(f"| {family[selected['family']]} | {products[symbol]} | {yen(a['profit'])} | {yen(a['loss'])} | {yen(a['net'],True)} | {a['trades']} | {a['payoff']:.2f} |")
    example = report.load(HERE/'results'/(report.EXAMPLE+'.json'))
    example_lines = []
    for symbol in ('TOPIX','NK225'):
        a = example['periods']['全28'][symbol]
        front = example['periods']['前16'][symbol]
        example_lines.append(f"| {products[symbol]} | {yen(a['profit'])} | {yen(a['loss'])} | {yen(a['net'],True)} | {a['trades']} | {yen(front['net'],True)} | {yen(a['without_best_session'],True)} |")
    result = '''# ティック入口とIFDトレールの検証結果

最初に見るファイルは[ティック入口とIFDトレールの損益](ティック入口とIFDトレールの損益.html)。各章で銘柄を切り替えると全28セッション・週別の利益／損失／収支、勝ち／負け枚数、5分足と新規／返済記録を確認できます。

**今回の192条件から、両銘柄で安定して損小利大を達成する方法は見つかっていません。** 両銘柄で全28の収支が黒字なのは1条件です。前16だけで選んだ4代表は全28で赤字でした。

## 前16だけで選んだ四代表

| 手法 | 商品 | 利益 | 損失 | 収支 | 決済数 | 1枚平均勝ち／負け比 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
'''+ '\n'.join(lines)+'''

4代表の設定IDと平易な入口説明は主HTMLに掲載。選定は各銘柄の前半20取引・8活動場以上が条件。単位を参照ラージ呼値に揃え、弱い銘柄の1取引平均の手数料後収支を最大化した。両銘柄黒字かつ平均勝ち／負け比>1という有望条件は全代表が未達。

## 一つだけあった両銘柄黒字例

**T3L1_E0_O16A8W8_H60：強い表示補充後の反転**。全28を見た事後の例で、前半の選定では日経の取引数不足（7回・5活動場）だった。

| 商品 | 利益 | 損失 | 収支 | 決済数 | 前16収支 | 最大黒字場を除いた収支 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
'''+ '\n'.join(example_lines)+'''

入口は、最良気配から2呼値以内の板数量が最良数量の1倍以上回復し、直近8中値イベントで4呼値以上その板へ接近していた場合。その後、接近方向に1呼値を超えて進む前に中値が4呼値反転し、買い・売り両気配も反転方向に動くと候補を出す。候補は120秒以内、場開始5分以降、気配差2呼値以下。板回復は観測上の代理で、真の補充注文・注文者・約定吸収は識別しない。

候補時の買いask／売りbidを親の新規逆指値価格とする。次の観測から条件を監視し、成立後の次の有効気配で仮想約定。新規成立後の次観測から、子の損切り16呼値と、親予約価格から8呼値順行して開始する幅8呼値の返済トレールをIFD-OCOで監視する。最長60分で返済判断、場内で全返済。

TOPIXの16／8／8呼値は8／4／4pt、日経は160／80／80円。子価格は親予約時点に固定する絶対価格で、実約定価格へ付け替えない。最終約定時計の同秒更新も原本行順に処理するため、実際の通信時間は再現していない。

全28での1枚平均勝ち／負け比はTOP0.93・日経0.89。平均勝ちより平均負けが大きく、最大黒字場を除くと両銘柄赤字。**黒字例があることと、安定性を確認できたことは別である。**

## なぜ赤字になるか

- 手数料前から赤字の条件はTOP185／192、日経180／192。手数料を外すだけでは解決しない。
- 再開型T2はTOP55.2%・日経54.6%勝っても、1枚平均勝ち／負け比は0.44／0.42。大きい損切りを小さい利確の頻度で埋められていない。
- 四代表の気配差負担は1取引平均約1.38〜1.55参照ラージ呼値、手数料はTOP0.1672・日経0.22呼値。細かく取引するほどこの負担が累積する。
- 標準補充反転T3の5分版はTOP973／1060・日経571／650回が保有期限返済。30・60分版も赤字であり、今回の条件では期限だけの問題ではない。
- 当初損切りの理由だけで「一度も順行しなかった」とは断定しない。今回の要約には全取引MFEを保持していない。

## 検証条件と正確性

入口4機構×2強度×親2設定×出口4設定×最長保有3設定＝192条件。親は候補時気配の新規逆指値又は幅2呼値の新規トレール。出口は(1)IFD純トレール4呼値、(2)損切り8・開始4・幅4、(3)損切り16・開始8・幅8、(4)損切り8・開始4・幅2のIFD-OCO。最長保有5／30／60分。ATR・移動平均は使用しない。

初回TOPIXmini5枚／NK225micro10枚、片方向上限10／20枚。増玉・両建てなし。買いは参照ラージask、売りはbidで約定。料金は片道1枚41.8／11円、新規と返済に課金し1注文合計を1円未満切捨て。利益・損失の会計へ既に含める。実小商品の気配、深さ、100%約定、通信・取消競合は再現しない。

保存28セッション（2026/09/21日中〜10/08夜間）、前16選定・後12比較。入口と取引判断は未来参照なし。ただし全28は既存研究で既知なので完全な未知データの試験ではない。途中切断・未来改変による同一過去出力、12人工経路、10,752口座・647,676注文・323,838決済の独立会計と約14億の含み時価行を照合済み。

現在場は状態APIを1回だけ確認。2026/10/09ナイトの対象両銘柄は0件だったため、現在板取得0・現在場バックテスト未実施・実注文0。ゼロ取引を成功に数えない。App/E01、過去の成果と元データは変更していない。

全192条件の全場会計と同一注文の非実行可能な中値感度は[全192条件の比較](全192条件の比較.html)。実装と証跡は[資料案内](README.md)。
'''
    (report.OUT/'検証結果.md').write_text(result,encoding='utf8')
    guide = '''# 作業00066：ティック入口とIFDトレール

**最初に見るファイル：[ティック入口とIFDトレールの損益](ティック入口とIFDトレールの損益.html)。** 四機構の短い説明、前半選定結果、全場・週会計、五分足と新規／返済記録、事後黒字例を掲載。

読む順序：

1. [主HTML](ティック入口とIFDトレールの損益.html)：4手法と各セッションの損益・枚数。
2. [全192条件の比較](全192条件の比較.html)：全条件の一覧と条件別の全28場会計。
3. [短い検証結果](検証結果.md)：黒字例の正確な入口・出口、赤字の原因、検証範囲。
4. [事前固定](../../work/wave_v69/事前固定.json)・[入口仕様](../../work/wave_v69/signals/入口仕様.json)・[選定証跡](../../work/wave_v69/機構別の前半選定.json)。
5. [監査の資料順](../../work/wave_v69/audit/README.md)・[報告説明の点検](../../work/wave_v69/audit/報告説明の点検.json)・[HTML照合](../../work/wave_v69/HTML表示の独立検査.json)。

## 実装と入力

- [ティック入口](../../work/wave_v69/signals/core.py)：中値反転・再開・表示補充反転・補充突破の8系列。
- [IFDと返済エンジン](../../work/wave_v69/engine.py)：親子の次観測監視、次行気配約定、IFD-OCO、保有期限・場内返済。
- [再生と会計](../../work/wave_v69/study.py)・[前半選定](../../work/wave_v69/select.py)・[レポート生成](../../work/wave_v69/report.py)。
- [入力照合](../../work/wave_v69/prepared/入力と特徴の照合.json)・[途中切断](../../work/wave_v69/prepared/追加特徴の途中切断検査.json)・[入口の因果検査](../../work/wave_v69/signals/入口の実原本因果照合.json)。
- [損失構造](../../work/wave_v69/analysis/損失構造.json)・[現在場の一回確認](../../work/wave_v69/current/現在場の確認.json)。

原本はbook、図はcandle_5min。全192の保存結果はwork/wave_v69/results、注文・決済台帳はledgers、固定入力はprepared。保存領域以外へ書き込まない。

再現用コマンド（プロジェクトルートから。Python・numpy・numbaが必要）：

```text
python -X utf8 work/wave_v69/study.py
python -X utf8 work/wave_v69/select.py
python -X utf8 work/wave_v69/report.py
```

study.pyは既存結果を再利用する。特定条件は--idsで指定。実装を変えた探索は新しい作業に分け、今回の事前固定を上書きしない。ネットワークを遮断して保存再生し、実注文は行わない。追加セッションは今回の既知28へ混ぜず、条件を固定した別検証として扱う。
'''
    (report.OUT/'README.md').write_text(guide,encoding='utf8')


def main() -> None:
    """機能: 監査とHTML照合のSHAを確認し、新作業を登録してリンクを検査する。

    引数: なし。返り値: なし(None)。
    """
    proof = report.load(HERE/'HTML表示の独立検査.json')
    audit = report.load(HERE/'audit/報告説明の点検.json')
    assert proof['全合格'] and proof['目視確認'] and proof['全条件表示']
    assert audit['合格']
    for filename,key in ((report.MAIN,'主HTML_SHA256'),(report.ALL,'全条件HTML_SHA256')):
        assert hashlib.sha256((report.OUT/filename).read_bytes()).hexdigest()==proof[key]==audit[key]
    fixed = report.load(HERE/'事前固定.json')
    assert all(hashlib.sha256((HERE/relative).read_bytes()).hexdigest()==value for relative,value in fixed['SHA256'].items())
    selection = report.load(HERE/'機構別の前半選定.json')
    documents(selection)
    folder = report.OUT.name
    source = INDEX.read_text(encoding='utf8').replace('class="task latest"','class="task"').replace(' <span class="badge">最新</span>','')
    source = re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00066：ティック反転・再開・補充・突破をIFDとトレールで192条件比較。28場の損益と売買図。</p>',source,count=1)
    block = f'''<!--00066開始--><article class="task latest"><div class="number">作業00066 <span class="badge">最新</span></div><h2>ティック入口とIFDトレール</h2><p>中値反転・押し戻し後の再開・補充後の反転・補充突破。192条件、保存28場、気配約定と手数料後の全場／週会計。少数黒字例と安定性を区別。</p><a class="button" href="{folder}/{report.MAIN}">ティック入口と損益を開く →</a><p><a href="{folder}/{report.ALL}">全192条件</a> · <a href="{folder}/検証結果.md">短い検証結果</a> · <a href="{folder}/README.md">資料案内</a></p></article><!--00066終了-->'''
    if '<!--00066開始-->' in source:
        source = re.sub(r'<!--00066開始-->.*?<!--00066終了-->',block,source,flags=re.S)
    else:
        source = source.replace('<!--00065開始-->',block+'\n<!--00065開始-->',1)
    INDEX.write_text(source,encoding='utf8')
    text = README.read_text(encoding='utf8').replace('**最新は00065','**00065')
    guide = f'''<!--00066案内開始-->
**最新は00066の[ティック入口とIFDトレールの損益]({folder}/{report.MAIN})。4機構・192条件を保存28場で比較。全場と週の利益／損失／収支・枚数、5分足売買図、少数の事後黒字例。**

[全192条件]({folder}/{report.ALL}) · [短い検証結果]({folder}/検証結果.md) · [資料案内]({folder}/README.md)。
<!--00066案内終了-->
'''
    if '<!--00066案内開始-->' in text:
        text = re.sub(r'<!--00066案内開始-->.*?<!--00066案内終了-->\n?',guide,text,flags=re.S)
    else:
        text = text.replace('<!--00065案内開始-->',guide+'\n<!--00065案内開始-->',1)
    README.write_text(text,encoding='utf8')
    # ----------------------------------------
    # 新旧のHTMLリンクと読む順に記載した全資料を確認する。
    count = 0
    for path in (INDEX,report.OUT/report.MAIN,report.OUT/report.ALL):
        for tag in BeautifulSoup(path.read_text(encoding='utf8'),'html.parser').select('a[href]'):
            href = tag['href']
            if href.startswith(('http','#')):
                continue
            target = (path.parent/unquote(href.split('?',1)[0].split('#',1)[0])).resolve()
            assert target.exists(),target
            count += 1
    for path in (README,report.OUT/'README.md',report.OUT/'検証結果.md'):
        for href in re.findall(r'\]\(([^)]+)\)',path.read_text(encoding='utf8')):
            if href.startswith(('http','#')):
                continue
            assert (path.parent/unquote(href.split('?',1)[0].split('#',1)[0])).resolve().exists(),href
            count += 1
    report.save(HERE/'公開リンク照合.json',dict(全合格=True,リンク数=count,最新作業='00066',公開先=str(report.OUT),
                                      事前固定SHA不変=True,実注文=0))
    print('00066を最新に登録、全リンク照合完了:',count)


if __name__=='__main__':
    main()

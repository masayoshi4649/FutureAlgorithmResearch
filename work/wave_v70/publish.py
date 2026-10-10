"""途中管理の検証結果と資料案内を保存し、最新作業へ登録する。"""

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
    """機能: 集計値を整数の円表示へ変換する。

    引数: value(float)、signed(bool)。返り値: 日本語の金額(str)。
    """
    return f'{value:+,.0f}円' if signed else f'{value:,.0f}円'


def documents() -> None:
    """機能: 保存会計から三代表の短い結果と資料案内を作る。

    引数: なし。返り値: なし(None)。
    """
    rows = []
    names = {'T2L0_H03':'段階保険の両建て','T2L0_N03':'同判断の縮小・復帰','T1L1_R01':'利益の段階固定'}
    for choice in report.study.load(HERE/'前半選定.json')['代表']:
        r = report.study.load(HERE/'results'/(choice['id']+'.json'))
        for symbol,product in (('TOPIX','TOPIXミニ10枚'),('NK225','日経マイクロ20枚')):
            a = r['periods']['全28'][symbol]
            payoff = (a['campaign_profit']/a['campaign_wins'])/(a['campaign_loss']/a['campaign_losses'])
            rows.append(f"| {names[choice['id']]} | {product} | {yen(a['campaign_profit'])} | {yen(a['campaign_loss'])} | {yen(a['net'],True)} | {a['campaigns']} | {payoff:.2f} |")
    result = '''# 両建て保険と途中管理の検証結果

**最初に見るファイル：[両建て保険と途中管理の説明と損益](両建て保険と途中管理の説明と損益.html)。** 3章で手法説明、同じ入口の対照、全28場と週の利益／損失／収支、枚数、5分足売買図を確認できます。

入口の精度だけでなく、保有中の増減・保険返済・持ち替えを試す必要があるという指摘は妥当です。6入口を固定し、32管理＝192条件を再生しました。段階両建て8、同判断の縮小復帰8、逆方向へ持ち替え4、分割利確4、時間による追跡幅短縮2、利益の段階固定4、全玉損失・利益保護1、基準1です。

## 前半で選んだ比較代表

**3代表とも採用条件は未達です。** 主要192条件では、両銘柄とも全28場で黒字の条件はありません。

| 管理 | 商品 | 組の利益 | 組の損失 | 収支 | 組数 | 1組平均利益／損失 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
'''+ '\n'.join(rows)+'''

一組は共通初回から管理終了まで。縮小復帰では実玉0枚の途中も仮想状態を監視し、同じ組で再建てできます。保険の利確や途中0枚だけを勝ちには数えません。部分決済の利益／損失と勝ち／負け枚数はHTMLの別表に掲載しています。

## 両建てはどの場面を助け、どの場面を壊したか

H03は押し戻し後の再開を入口に、TOP10枚／NK20枚を建てます。逆行8参照ラージ呼値ごとに約25%の保険を追加（TOP3枚／NK5枚、最後は残枠）。保険全体の平均利益4呼値で追跡を開始し、4呼値反転しても手数料後利益が見込める時に保険を全返済します。元玉の損切り32呼値、最長60分、場内全返済です。

- **改善例**：TOPIX 09/29デイの4組目。元玉+4,164円に保険+30,749円が加わり、一組+34,913円。同じ損失枠で保険なしなら+4,164円でした。
- **悪化例**：TOPIX 10/08デイの4組目。元玉+84,164円が、保険−90,500円によって一組−6,336円になりました。

元玉が逆行する途中に保険を建てるので、逆行継続中の被害は減ります。一方、元方向へ回復すると保険が損失玉になります。「利益が出た保険だけ返済する」条件ではその損失玉を単独で切れず、元玉の利確まで残る場合があります。終端で元玉と保険を全部返す損失と費用を含めると、今回のルールは全体を悪化させました。

基準B00は元玉stop16呼値、H03は32呼値なので、両者の差だけでは保険の効果を切り分けられません。そこで結果を見た後に、H03と損失枠・期限を揃えて保険だけ外したD32など30条件を追加診断しました。**H03はD32に対しTOP−609,258円／NK−316,570円。改善した場は7／28・6／28でした。** 診断30で初192の選定は変更していません。

## 縮小・復帰の意味

N03はH03と全く同じ判断で、保険新規の代わりに元玉を部分返済し、保険利確の代わりに元方向へ再建てします。価格に対するネット枚数は同じです。

終端に残った両建ての余分な往復を省けるため、N03はH03よりTOP+208,822円／NK+120,980円でした。差は終端の気配差TOP187,500円／NK108,000円と、手数料TOP21,322円／NK12,980円に全場で一致しました。これは「両建ての保険利確だけ見れば儲かる」という見かけを避ける対照です。両建てが別の価格予測能力を生むわけではありません。

## 利益固定は改善したが、損小利大は未達

T1L1_R01は中値の反転で満額新規。4参照ラージ呼値進むごとに、その段階の利益を保護する逆指値を準備します。保護線は次の観測から有効です。TOPの4呼値は2pt、NKは40円です。元玉stop16、通常trail8、最長60分も監視します。

同じ入口B00からの変更で、負け組の損失合計はTOP35.9%／NK37.8%減り、収支は−1,061,880円→−436,880円／−461,280円→−219,280円へ改善しました。ただし勝ち組の利益も17.1%／29.9%減っています。組勝率73.8%／75.9%でも平均利益／損失は0.25／0.23。**損失合計の減少は、残る一敗が小さくなったことを意味しません。** 残った負けの平均額はむしろ増えました。

## 追加診断の黒字例は別扱い

T3L1_D32とT3L1_D32A16W8は同じ売買経路で、全28場TOP+234,068円／NK+1,840円でした。2つの独立した勝ち方ではありません。TOP37組／NK14組、前16のNKは6組で−78,640円。平均勝組／負組比は0.85／0.76、最大黒字場を除くとTOP+740円／NK−47,280円です。結果を見た後の原因診断なので、前半選定の候補には加えていません。

## 検証範囲

保存28場（09/21デイ〜10/08ナイト）。同じ初回時刻・方向・満額数量を使い、初回から3630秒は次の親予約を待ちます。早く返済しても入口数を変えない共通60分枠の比較です。**00066や旧E01／R01の通し運用を再現した損益ではありません。** E01P／R01Pは旧ATR・EMAの入口状態の開始／方向変更だけを部品として使用し、旧台帳の入口行は参照していません。

TOPIXミニは片方向10枚、日経マイクロは片方向20枚が上限。反対玉も同じ上限内です。買いask／売りbid、判断した次の有効原本行で仮想約定。参照ラージの板と呼値（TOP0.5pt／NK10円）を使っています。片道1枚41.8円／11円、新規と返済の各注文合計を1円未満切捨て。利益と損失は料金控除済み、全原本行の両方向含み損益と最大保有枚数を記録しています。

主要10,752口座と追加1,680口座の独立会計、同じ初回列、部分料金、売買方向の反射、人工経路、途中切断・未来変更、前半順位、両建てと縮小対照の全原本行の恒等式を照合済み。保存28場は既知なので、未知期間の試験とは区別しています。現在API取得0、実注文0。実商品の板・深さ・通信遅延・取消競合は再現していません。

**未検証**：損失保険の独立損切り、元方向再開時の保険削減、再展開の冷却、各段の独立IFD、分割利確後の再増玉、取消照合を含む実時間執行。今回の結果で全ての管理テクニックを無効と結論するものではありません。

全222条件の会計は[全条件の途中管理比較](全条件の途中管理比較.html)。実装と監査は[資料案内](README.md)。
'''
    (report.OUT/'検証結果.md').write_text(result,encoding='utf8')
    guide = '''# 作業00067：両建て保険と途中管理

**最初に見るファイル：[両建て保険と途中管理の説明と損益](両建て保険と途中管理の説明と損益.html)。** 3比較代表の短い説明、全28場・週の利益／損失／収支・枚数、5分足の新規／返済図を掲載。

読む順序：

1. [主HTML](両建て保険と途中管理の説明と損益.html)：段階両建て・同判断の縮小復帰・利益固定。
2. [全条件の途中管理比較](全条件の途中管理比較.html)：主要192と追加診断30の全条件・全28場会計。
3. [短い検証結果](検証結果.md)：保険の改善／悪化例、同幅対照、未検証の管理。
4. [主要の事前固定](../../work/wave_v70/事前固定.json)・[前半選定](../../work/wave_v70/前半選定.json)・[追加診断の事前固定](../../work/wave_v70/追加対照の事前固定.json)。
5. [独立監査の資料順](../../work/wave_v70/audit/README.md)・[公開説明の監査](../../work/wave_v70/audit/公開説明と会計の最終監査.json)・[全HTML表示照合](../../work/wave_v70/HTML表示の独立検査.json)。

## 実装と証跡

- [共通入口の資料順](../../work/wave_v70/inputs/README.md)・[入口仕様](../../work/wave_v70/inputs/入口仕様.json)・[共通入口スケジュール仕様](../../work/wave_v70/inputs/共通入口スケジュール仕様.json)。
- [途中管理エンジン](../../work/wave_v70/engine.py)：逆行グリッド、保険全体トレール、持ち替え、分割、時間短縮、利益固定、全玉の損失／利益枠。
- [縮小復帰の写像](../../work/wave_v70/net.py)・[再生と会計](../../work/wave_v70/study.py)・[保険を外した同幅診断](../../work/wave_v70/controls.py)。
- [理論と事前仮説](../../work/wave_v70/theory/管理手法の事前仮説.md)・[管理の効果と限界](../../work/wave_v70/analysis/管理の効果と限界.json)。
- [レポート生成](../../work/wave_v70/report.py)・[表示検査](../../work/wave_v70/verify.py)。

原本bookと図candle_5minは読取専用。主要結果はwork/wave_v70/results、注文・部分決済台帳はledgers。追加診断はcontrols/resultsとcontrols/ledgersへ分離。現在API取得0、実注文0。App/E01と過去の成果は変更していません。

## 再現

プロジェクトルートから実行（Python・numpy・numbaが必要。ブラウザ表示検査にはBeautifulSoupとChromeも使用）：

```text
python -X utf8 work/wave_v70/study.py
python -X utf8 work/wave_v70/controls.py
python -X utf8 work/wave_v70/select.py
python -X utf8 work/wave_v70/report.py
python -X utf8 work/wave_v70/verify.py
```

既存結果を再利用します。--freezeは今回の固定ファイルを再作成するので再現時には付けません。実装を変える研究と追加セッションは新しい作業に分けます。前16で選んだ代表を後12や追加診断の収支で入れ替えません。verify.pyは目視欄を未確認へ戻すため、画像を見てから目視確認を記録します。

実注文用アプリの改修ではなく、保存板の因果的な途中管理比較です。複数管理条件の更新を実注文へ移す際の取消・照合・部分約定は未実装です。
'''
    (report.OUT/'README.md').write_text(guide,encoding='utf8')


def main() -> None:
    """機能: 監査・公開SHA・資料リンクを確認し最新00067を登録する。

    引数: なし。返り値: なし(None)。
    """
    proof = report.study.load(HERE/'HTML表示の独立検査.json')
    audit = report.study.load(HERE/'audit/公開説明と会計の最終監査.json')
    assert proof['全合格'] and proof['全条件表示'] and proof['目視確認'] and audit['合格']
    for filename,key in ((report.MAIN,'主HTML_SHA256'),(report.ALL,'全条件HTML_SHA256')):
        assert hashlib.sha256((report.OUT/filename).read_bytes()).hexdigest()==proof[key]==audit[key]
    fixed = report.study.load(HERE/'事前固定.json')
    assert all(hashlib.sha256((report.ROOT/path).read_bytes()).hexdigest()==digest for path,digest in fixed['SHA256'].items())
    documents()
    folder = report.OUT.name
    source = INDEX.read_text(encoding='utf8').replace('class="task latest"','class="task"').replace(' <span class="badge">最新</span>','')
    source = re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00067：段階両建て・元玉縮小復帰・持ち替え・利益固定など32管理を、同じ入口で比較。保存28場の損益と売買図。</p>',source,count=1)
    block = f'''<!--00067開始--><article class="task latest"><div class="number">作業00067 <span class="badge">最新</span></div><h2>両建て保険と途中管理</h2><p>6入口×32管理の192条件と、保険だけを外した追加30診断。同じ満額入口・全玉含み損益・手数料で比較。TOPIXミニ10枚／日経マイクロ20枚、全28場と週の損益・枚数・5分足売買図。</p><a class="button" href="{folder}/{report.MAIN}">途中管理と損益を開く →</a><p><a href="{folder}/{report.ALL}">全222条件</a> · <a href="{folder}/検証結果.md">短い検証結果</a> · <a href="{folder}/README.md">資料案内</a></p></article><!--00067終了-->'''
    if '<!--00067開始-->' in source:
        source = re.sub(r'<!--00067開始-->.*?<!--00067終了-->',block,source,flags=re.S)
    else:
        assert '<!--00066開始-->' in source
        source = source.replace('<!--00066開始-->',block+'\n<!--00066開始-->',1)
    INDEX.write_text(source,encoding='utf8')
    text = README.read_text(encoding='utf8').replace('**最新は00066','**00066')
    guide = f'''<!--00067案内開始-->
**最新は00067の[両建て保険と途中管理の説明と損益]({folder}/{report.MAIN})。32管理×6入口、追加30診断、保存28場。段階両建て・縮小復帰・利益固定の説明、全場と週の損益・枚数、5分足売買図。**

[全222条件]({folder}/{report.ALL}) · [短い検証結果]({folder}/検証結果.md) · [資料案内]({folder}/README.md)。
<!--00067案内終了-->
'''
    if '<!--00067案内開始-->' in text:
        text = re.sub(r'<!--00067案内開始-->.*?<!--00067案内終了-->\n?',guide,text,flags=re.S)
    else:
        assert '<!--00066案内開始-->' in text
        text = text.replace('<!--00066案内開始-->',guide+'\n<!--00066案内開始-->',1)
    README.write_text(text,encoding='utf8')
    # ----------------------------------------
    # 新旧一覧と新作業に記した資料リンクを確認する。
    count = 0
    for path in (INDEX,report.OUT/report.MAIN,report.OUT/report.ALL):
        for tag in BeautifulSoup(path.read_text(encoding='utf8'),'html.parser').select('a[href]'):
            href = tag['href']
            if href.startswith(('http','#')):
                continue
            assert (path.parent/unquote(href.split('?',1)[0].split('#',1)[0])).resolve().exists(),href
            count += 1
    for path in (README,report.OUT/'README.md',report.OUT/'検証結果.md'):
        for href in re.findall(r'\]\(([^)]+)\)',path.read_text(encoding='utf8')):
            if href.startswith(('http','#')):
                continue
            assert (path.parent/unquote(href.split('?',1)[0].split('#',1)[0])).resolve().exists(),href
            count += 1
    report.study.save(HERE/'公開リンク照合.json',dict(全合格=True,リンク数=count,最新作業='00067',公開先=str(report.OUT),
                                                 事前固定SHA不変=True,現在API取得=0,実注文=0))
    print('00067を最新に登録、全リンク照合完了:',count)


if __name__=='__main__':
    main()

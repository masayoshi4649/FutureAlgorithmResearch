"""二指数共同方向の検証資料を、表示確認後に作業00071として案内する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00071_二指数の共同方向と先行追随'
MAIN='二指数を同時に見る手法と全セッション損益.html'
ALL='全336条件の比較.html'


def read(path: Path) -> dict:
    """機能: 保存した会計・監査・表示確認を読み取る。

    引数: path(Path)。返り値: 保存内容(dict)。
    """
    return json.loads(path.read_text(encoding='utf8'))


def documents() -> None:
    """機能: 最初に見る資料、読む順序と再現条件を案内する。

    引数: なし。返り値: なし(None)。今回の公開フォルダだけに保存する。
    """
    source=f'''# 作業00071：二指数の共同方向と先行追随

**最初に見るファイル：[{MAIN}]({MAIN})。**

読む順序：

1. 主HTML：短い結論、7方式の結果、3代表の入口／途中／出口、全29セッションと週の金額損益、五分足と売買位置。
2. [{ALL}]({ALL})：共同判定168条件と自市場証拠の対照168条件。条件別の全セッション損益も確認できます。
3. [公開会計](公開会計.json)：HTMLへ渡した代表の会計資料。
4. [事前固定](../../work/wave_v75/事前固定.json)・[前半選定](../../work/wave_v75/前半選定.json)：損益計算前の条件と前16セッションによる代表選定。
5. [二指数情報の追加価値と遅延感度](../../work/wave_v75/analysis/二指数情報の追加価値と遅延感度.json)・[同じ新規機会での相手確認診断](../../work/wave_v75/analysis/同じ新規機会での相手確認診断.json)：共同判定と対照の差、1／5／15／60秒の情報遅延、同一売買を用いた確認あり／なしの比較。
6. [市場原理と研究資料](../../work/wave_v75/theory/二指数を同時に見る事前仮説.json)・[入力資料案内](../../work/wave_v75/inputs/README.md)：仮説の根拠、時計・欠測・同期の限界。
7. [監査フォルダ](../../work/wave_v75/audit/)・[表示検査フォルダ](../../work/wave_v75/review/)：独立会計、原本順序、片側の未来変更、表と売買図の検査。

## 今回分かったこと

J1の「両市場が進行し、直近も方向を維持する」は継続検証する候補です。選定済みの設定は5分変化0.03%以上、直近15秒で売買両気配が1呼値進み、相手も逆行していない場合に同方向へ建てます。トレール幅は観測済み始値の0.4%、30分で返済を判断し、場内で全返済します。ATRは使いません。

主5秒遅延・全29場で、TOPIXミニ10枚は利益2,743,200円／損失1,970,932円／収支+772,268円、NK225マイクロ20枚は利益1,107,520円／損失778,960円／収支+328,560円でした。同じ出口で相手の内容を使わない対照はそれぞれ+276,464円／+164,960円です。前16・後13とも両商品黒字で、各期間の最大黒字場を除いても黒字です。

入口時刻の違いを切り分けるため、S1の同じ実取引142件を判断時点の相手確認あり／なしへ分類しました。1取引平均はTOPの確認あり+9,776円／なし−7,503円、NKは+5,910円／−2,748円です。前半・後半とも確認ありが上回りました。これは同じ売買の分類診断で、確認なしを実際に除いた新戦略の再生ではありません。

ただし後13のNKは平均勝ち額／平均負け額が0.96で、事前に定めた厳しい有望条件を全て満たしたわけではありません。60秒遅延の全29場ではNKが−14,760円へ悪化しました。また日々の改善は一様ではなく、下落幅の増大もあるため、実運用採用が確定したとは扱いません。

前半の選定順位はJ7→J1→J3のままです。後半を見て代表を差し替えていません。上記のJ1評価は7方式それぞれの確認結果を比較したものです。J4・J5・J6は前半の最低取引数又は活動場数が不足し、比較例として掲載します。

## 金額・枚数の読み方

- 利益：手数料後に黒字だった全決済の合計。
- 損失：手数料後に赤字だった全決済の絶対額合計。
- 収支：利益−損失。手数料は二重に引きません。
- 金額損失割合：損失÷（利益＋損失）。50%未満なら総収支が黒字です。無取引は未定義です。
- 平均勝ち／負け：1決済の平均黒字額÷平均赤字額。総利益／総損失とは異なります。

TOPIXミニ10枚、NK225マイクロ20枚は別々の独立口座です。円金額を両商品で足して順位を決めません。両方のラージ板を参照し、各商品の取引判断をします。NT倍率の両脚を同時に組むペア取引ではありません。全建玉を返済しており、負け玉を残して黒字だけ集計する処理はありません。

## 何を比べたか

保存データ2026-09-21デイ〜2026-10-09デイの29場を使用。共同方向・先行追随・先行失敗・相対価格の戻り・両板の圧力先行・片側の吸収失敗・事前順序の自動選択の7方式です。各方式で窓60／300秒、強度2種類、返済幅0.1／0.2／0.4%、保有期限30／60分を比較し、相手の内容を用いない対照を含む336条件です。

両市場の観測が揃う時点は共同と対照で共通です。ただし条件の成立・解消で再準備が変わるため、売買機会が完全一致する介入実験ではありません。第4方式の対照は自市場価格の平均回帰であり、単なる相手条件の除去とは区別します。

前16だけで両商品20取引以上・活動8場以上を要求し、銘柄別金額損失割合の悪い側から評価。後13で差し替えず、代表の設定を固定したまま情報遅延1／15／60秒でも再生しました。この29場は過去にも研究した既知データであり、未知の将来検証ではありません。

## 同期・約定・費用

共通の予定時刻から15秒ごとに判定。主計算は5秒引いた期限より厳密に過去の観測を使用し、同一時計値の先頭行だけを採用します。期限から30秒より古い情報・異常・途中の切断は使わず、相手の欠測を中立へ補完しません。鮮度30秒は損益を見る前に入力取得率で選びました。

幅の基準には当該セッションの時刻付きOpeningPriceを使い、古いセッションの値しかない場合は初めて観測したCurrentPriceを使います。今回の全58口座で最初の入力行から既知であることを確認しています。

原本板のCurrentPriceTimeは最終約定の時計で、共通の受信時刻はありません。未来切断や遅延感度に合格しても、実配信で同時利用できたことやミリ秒の先行関係を証明するものではありません。

新規条件は判断時刻以上の最初の原本行へ写像し、10秒を超える遅れや悪い板では取り消します。さらにその次の有効気配で買いはask、売りはbidへ仮想約定。保有後も各原本行でトレール・時間上限・場末を監視し、返済判断後の次有効気配で返済します。保存末尾を知って返済する処理はありません。

全量1回の保有、追加玉・両建て・持越しなし。各新規の発火後は有効な中立状態の連続60秒と、発火間隔600秒が必要です。欠測で再準備しません。場内返済判断はデイ15:34／ナイト05:49から。気配の欠測により判断から約定まで遅れる場合があります。

片道手数料はTOPIXミニ41.8円、NK225マイクロ11円を枚数倍し、注文合計の1円未満切捨て。売買気配差は約定値に含まれます。ミニ／マイクロの執行もラージ板による代理であり、実商品の気配・板深さ・順番待ちは未再現です。

現在セッションAPI取得0、実注文0。原本book/candleは変更せず、実運用アプリも変更していません。

## 再現

計算本体は[study.py](../../work/wave_v75/study.py)、二市場の入口は[signals.py](../../work/wave_v75/signals.py)、注文再生は[engine.py](../../work/wave_v75/engine.py)です。

```text
python -X utf8 work/wave_v75/study.py --workers 6
python -X utf8 work/wave_v75/study.py --delay 1
python -X utf8 work/wave_v75/study.py --delay 15
python -X utf8 work/wave_v75/study.py --delay 60
python -X utf8 work/wave_v75/analysis/compare_joint.py --delay-dir 1=sensitivity/delay1/results --delay-dir 15=sensitivity/delay15/results --delay-dir 60=sensitivity/delay60/results
python -X utf8 work/wave_v75/report/generate.py
```

保存済み条件は計算を省略します。事前固定・選定・入口保存は完了済みで、上書きしません。完全な再計算は今回フォルダを複製し、出力先を分けて行います。
'''
    (OUT/'README.md').write_text(source,encoding='utf8')


def links(paths: list[Path]) -> int:
    """機能: 公開資料と索引のローカル参照先を検査する。

    引数: paths(list[Path])。返り値: 確認したリンク数(int)。
    """
    count=0
    for path in paths:
        source=path.read_text(encoding='utf8')
        refs=([a['href'] for a in BeautifulSoup(source,'html.parser').select('a[href]')]
              if path.suffix=='.html' else re.findall(r'\]\(([^)]+)\)',source))
        for href in refs:
            if href.startswith(('http:','https:','#')):
                continue
            target=path.parent/unquote(href.split('#',1)[0].split('?',1)[0])
            assert target.exists(),(path,href)
            count+=1
    return count


def main() -> None:
    """機能: 監査・表示確認後に00071を最新の作業として登録する。

    引数: なし。返り値: なし(None)。過去の作業フォルダは変更しない。
    """
    ready=read(HERE/'review/公開前確認.json')
    assert ready['監査確認'] and ready['目視確認'] and ready['全合格']
    for name in (MAIN,ALL):
        assert hashlib.sha256((OUT/name).read_bytes()).hexdigest()==ready['HTML_SHA256'][name]
    documents()
    folder=OUT.name
    index=ROOT/'アルゴリズム調査/index.html'
    readme=ROOT/'アルゴリズム調査/README.md'
    source=index.read_text(encoding='utf8').replace('class="task latest"','class="task"').replace(' <span class="badge">最新</span>','')
    source=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00071：NK225FとTOPIXFの共同方向・先行追随・板圧力を336条件で比較。全29場の損益と単独対照、情報遅延への感度。</p>',source,count=1,flags=re.S)
    block=f'''<!--00071開始--><article class="task latest"><div class="number">作業00071 <span class="badge">最新</span></div><h2>二指数の共同方向と先行追随</h2><p>両銘柄の関係から7方式を作り、同じ出口の単独対照と比較。共同方向のJ1は両商品で前半・後半とも黒字。全29場の利益・損失・収支、五分足売買図、1〜60秒の情報遅延も掲載。</p><a class="button" href="{folder}/{MAIN}">説明と全セッション損益を開く →</a><p><a href="{folder}/{ALL}">全336条件の比較</a> · <a href="{folder}/README.md">資料案内</a> · <a href="{folder}/公開会計.json">公開会計</a></p></article><!--00071終了-->'''
    if '<!--00071開始-->' in source:
        source=re.sub(r'<!--00071開始-->.*?<!--00071終了-->',block,source,flags=re.S)
    else:
        assert '<!--00070開始-->' in source
        source=source.replace('<!--00070開始-->',block+'\n<!--00070開始-->',1)
    # ----------------------------------------
    # 過去へのリンクを残し、最新の案内だけを更新する。
    text=readme.read_text(encoding='utf8').replace('**最新は00070','**00070')
    guide=f'''<!--00071案内開始-->
**最新は00071の[二指数を同時に見る手法と全セッション損益]({folder}/{MAIN})。二市場の共同方向・先行追随・不一致・板圧力の7方式、対照込み336条件。TOPIXミニ10枚／NK225マイクロ20枚、全29場の金額損益と情報遅延への感度。**

[全336条件]({folder}/{ALL}) · [資料案内]({folder}/README.md) · [公開会計]({folder}/公開会計.json)。
<!--00071案内終了-->
'''
    if '<!--00071案内開始-->' in text:
        text=re.sub(r'<!--00071案内開始-->.*?<!--00071案内終了-->\n?',guide,text,flags=re.S)
    else:
        assert '<!--00070案内開始-->' in text
        text=text.replace('<!--00070案内開始-->',guide+'\n<!--00070案内開始-->',1)
    index.write_text(source,encoding='utf8')
    readme.write_text(text,encoding='utf8')
    count=links([index,readme,OUT/MAIN,OUT/ALL,OUT/'README.md'])
    (HERE/'公開リンク照合.json').write_text(json.dumps(dict(合格=True,照合リンク数=count,最新='00071'),ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(合格=True,照合リンク数=count),ensure_ascii=False))


if __name__=='__main__':
    main()

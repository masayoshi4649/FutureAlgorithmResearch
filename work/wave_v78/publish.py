"""歴代手法の再評価と固定した統合条件を、過去資料を保って案内する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00074_歴代手法の再評価と二市場統合'
MAIN='過去の知見を統合した手法と全セッション損益.html'
ALL='全162条件の比較.html'


def documents() -> None:
    """機能: 最初に見る資料、短い結論、再現方法を保存する。

    引数: なし。返り値: なし(None)。
    """
    text=f'''# 作業00074：歴代手法の再評価と二市場統合

**最初に見るファイル：[{MAIN}]({MAIN})。**

読む順序：

1. 主HTML：現本命、歴代10系統の採否、固定3代表と従来J2、入口・途中・出口、全30セッションと五分足・全注文。
2. [{ALL}]({ALL})：事前固定162条件の両商品・全30場。全条件を同じ気配・手数料・枚数で比較。
3. [公開会計](公開会計.json)、[部品の効果](../../work/wave_v78/evidence/統合部品の効果と失敗.json)、[相場方向別の事後診断](../../work/wave_v78/evidence/相場方向別の事後診断.json)。
4. [古典候補](../../work/wave_v78/evidence/歴代主力の再評価.json)、[最近の候補](../../work/wave_v78/evidence/最近の候補と再利用できる部品.json)。
5. [事前固定](../../work/wave_v78/事前固定.json)、[前半選定](../../work/wave_v78/前半選定.json)、[仮説と原著](../../work/wave_v78/theory/統合前の敵対仮説.json)。
6. [独立監査](../../work/wave_v78/audit/README.md)、[表示検査](../../work/wave_v78/report/)。

## 結論

**現時点の本命は、両市場の共通価格進行を選ぶ従来J2（J2_F0_B0_H0_R0）です。ただし、全日安定して損小利大を達成する完成形は見つかっていません。**

板の反対一致で降りる統合案J2_F1_B0_H0_R0は、前16で固定された新主候補です。全30の収支は従来よりTOPIX+50,000円、日経+8,000円ですが、後14のTOPIXでは−75,000円悪化。後14の最大利益日を除くと−73,424円になり、事前の後半合格条件を満たしません。後半で別の新条件を選び直さず、従来からの基準J2を維持します。

| 従来J2・手数料後 | TOPIXミニ10枚 | 日経225マイクロ20枚 |
| --- | ---: | ---: |
| 総利益 | 2,566,544円 | 1,087,960円 |
| 総損失 | 1,833,424円 | 600,320円 |
| 収支 | +733,120円 | +487,640円 |
| 金額利益割合 | 58.33% | 64.44% |
| 平均勝ち／平均負け | 1.035倍 | 1.238倍 |
| 黒字／赤字／無取引セッション | 18／11／1 | 19／8／3 |
| 最大利益日除外の収支 | +342,300円 | +330,720円 |
| 最大清算時価下落 | 485,064円 | 175,760円 |

両商品とも3週それぞれの合計、デイ合計・ナイト合計が黒字。情報遅延1・5・15秒でも全体黒字ですが、1秒の日経の平均勝ち／負けは0.982倍。後14のTOPIXは最大利益日を除くと+1,576円しか残らず、余裕は薄いです。金額利益80%・両商品の全30場黒字は今回162条件とも未達です。

**相場方向別でも弱点があります。** 保存5分足の最初の始値→最後の終値で事後分類すると、双方上昇12場のTOPIXは−628,408円／日経+191,880円、双方下落11場は+857,412円／+267,680円、逆方向7場は+504,116円／+28,080円。上昇・下落を問わず安定した方式とは認定できません。この分類は説明専用であり、将来終値を使う手法切替はしていません。始終の符号は場内で一方向だったという意味でもありません。

## 機械的な売買条件

- 入口：両市場の過去300秒中値が同方向へ各0.03%以上進み、自市場の直近15秒の売買両気配が同方向へ1呼値以上、相手の短期価格が逆行しない。明確な逆向きOFIがなく、弱い側の300秒進行量が強い側の25%以上で新規。
- 途中：全量初回、TOPIX10枚／日経20枚。同じ0.4%幅を保つ。ATR・機械学習は使わない。
- 出口：当場始値0.4%幅を最低2呼値へ切り上げ、建値から常時トレーリング。返済側気配の順行極値を追う。30分又は場内撤収時刻でも全返済。返済後30秒は新規を待つ。

J0/J1/J2の入口に、反対撤退3・建値保護3・保有期限3・連敗休止2を組み合わせ162条件を事前固定しました。早期保護でもトレール幅0.4%は変更せず、従来の幅縮小との混同を解消しています。保有延長、連敗休止も単独・組合せで完全再運転しています。

## 検証の範囲

全30場は既知資料。前16選定・後14確認は時間順の再評価であり、新しい未知相場の検証ではありません。今回の候補を固定した後に後半結果で差し替えていません。

判断は5秒格子、主比較の情報遅延5秒。代理時計の厳密過去・同時計先頭だけを参照します。約定は判断後の次有効ラージ気配、買ask・売bid。実際のミニ・マイクロ自身の気配、約定待ち順位、市場影響は未再現です。保護線通りの約定は保証しません。

料金は片道TOPIX41.8円／日経11円を注文全体で円未満切捨て。商品ごとに勝ち金額と負け金額を比較し、異なる倍率の円を合算しません。全玉場内返済、未決済末尾の架空清算なし。日・週はセッション開始日帰属。夜間も開始日のデイとまとめます。無取引を勝ちに数えません。

旧E01などは期間・費用・約定モデルが異なるため今回と円収支だけで順位付けしません。元データ・過去レポート・実運用アプリは変更せず、現在API取得0、実注文0です。

## 再現

```text
python -X utf8 work/wave_v78/study.py --workers 6
python -X utf8 work/wave_v78/study.py --delay 1 --workers 3
python -X utf8 work/wave_v78/study.py --delay 15 --workers 3
python -X utf8 work/wave_v78/report/generate.py
```

固定・選定済みの資料は上書きしません。保存済み結果の再生は省略します。全再計算は別出力先を用意してください。実装は[study.py](../../work/wave_v78/study.py)・[signals.py](../../work/wave_v78/signals.py)・[engine.py](../../work/wave_v78/engine.py)です。
'''
    (OUT/'README.md').write_text(text,encoding='utf8')


def links(paths: list[Path]) -> int:
    """機能: 公開資料と索引のローカルリンク先を検査する。

    引数: paths(list[Path])。返り値: 検査数(int)。
    """
    count=0
    for path in paths:
        source=path.read_text(encoding='utf8')
        refs=[a['href'] for a in BeautifulSoup(source,'html.parser').select('a[href]')] if path.suffix=='.html' else re.findall(r'\]\(([^)]+)\)',source)
        for href in refs:
            if href.startswith(('http:','https:','#')):continue
            assert (path.parent/unquote(href.split('#',1)[0].split('?',1)[0])).exists(),(path,href)
            count+=1
    return count


def main() -> None:
    """機能: 独立監査と目視済みの資料だけを最新の案内へ登録する。

    引数: なし。返り値: なし(None)。
    """
    proof=json.loads((HERE/'report/公開前確認.json').read_text(encoding='utf8'))
    assert proof['全合格'] and proof['監査確認'] and proof['目視確認']
    for name in (MAIN,ALL):assert hashlib.sha256((OUT/name).read_bytes()).hexdigest()==proof['HTML_SHA256'][name]
    documents();folder=OUT.name;index=ROOT/'アルゴリズム調査/index.html';readme=ROOT/'アルゴリズム調査/README.md'
    source=index.read_text(encoding='utf8').replace('class="task latest"','class="task"').replace(' <span class="badge">最新</span>','')
    source=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00074：歴代手法を再評価し162通りで統合を検証。共通価格進行のJ2を土台に維持。全日安定・金額利益80%は未達。</p>',source,count=1,flags=re.S)
    block=f'''<!--00074開始--><article class="task latest"><div class="number">作業00074 <span class="badge">最新</span></div><h2>歴代手法の再評価と二市場統合</h2><p>入口・途中・出口の部品を162通りで比較。基準J2を本命に維持し、板反対撤退の改良は後半TOPIX悪化で昇格保留。両商品全30場の損益、週別、五分足・全注文を掲載。</p><a class="button" href="{folder}/{MAIN}">説明と全セッション損益を開く →</a><p><a href="{folder}/{ALL}">全162条件の比較</a> · <a href="{folder}/README.md">資料案内</a> · <a href="{folder}/公開会計.json">公開会計</a></p></article><!--00074終了-->'''
    if '<!--00074開始-->' in source:source=re.sub(r'<!--00074開始-->.*?<!--00074終了-->',block,source,flags=re.S)
    else:
        assert '<!--00073開始-->' in source;source=source.replace('<!--00073開始-->',block+'\n<!--00073開始-->',1)
    guide=f'''<!--00074案内開始-->
**最新は00074の[{MAIN}]({folder}/{MAIN})。歴代を再評価し162条件で統合。現本命は基準J2、板反対撤退の追加は昇格保留。全日安定・金額利益80%は未達。**

[全162条件]({folder}/{ALL}) · [資料案内]({folder}/README.md) · [公開会計]({folder}/公開会計.json)。
<!--00074案内終了-->
'''
    text=readme.read_text(encoding='utf8').replace('**最新は00073','**00073')
    if '<!--00074案内開始-->' in text:text=re.sub(r'<!--00074案内開始-->.*?<!--00074案内終了-->',guide.strip(),text,flags=re.S)
    else:text=text.replace('<!--00073案内開始-->',guide+'\n<!--00073案内開始-->',1)
    # ----------------------------------------
    # 既往の作業本文は保存したまま、総合索引の案内だけを追加する。
    index.write_text(source,encoding='utf8');readme.write_text(text,encoding='utf8')
    count=links([index,readme,OUT/'README.md',OUT/MAIN,OUT/ALL])
    (HERE/'report/公開案内検査.json').write_text(json.dumps(dict(合格=True,リンク数=count,新作業=folder),ensure_ascii=False,indent=2),encoding='utf8')
    print(f'00074の案内と{count}リンクを確認しました')


if __name__=='__main__':
    main()

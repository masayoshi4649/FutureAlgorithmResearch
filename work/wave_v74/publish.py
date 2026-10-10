"""作業00070の資料案内と検証済みHTMLへの入口を公開する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT/'アルゴリズム調査/00070_始値と前終値の方向制限と連敗休止'
MAIN = '基準価格と連敗休止の説明と全セッション損益.html'
ALL = '全480条件の比較とセッション損益.html'
EXTRA = '新規方向だけを制限する方式の損益.html'
EXTRA_ALL = '追加240条件の比較とセッション損益.html'


def read(path: Path) -> dict:
    """機能: 固定した検証証跡を読み取る。

    引数: path(Path)。返り値: 証跡(dict)。
    """
    return json.loads(path.read_text(encoding='utf8'))


def documents() -> None:
    """機能: 最初に見るHTML、読む順序、再現方法を記載する。

    引数: なし。返り値: なし(None)。今回フォルダだけに保存する。
    """
    text=f'''# 作業00070：始値と前終値の方向制限と連敗休止

**最初に見るファイル：[{MAIN}]({MAIN})。**

読む順序：

1. 主HTML：始値・前保存場・両基準一致の3章。入口／途中／出口、銘柄別の損益、休止だけの比較、全29セッション、週、五分足と新規返済。
2. [{EXTRA}]({EXTRA})：基準跨ぎ時の即返済をやめ、新規方向だけを制限する追加検証。最初の解釈による即返済の影響を切り分けます。
3. [{ALL}]({ALL})・[{EXTRA_ALL}]({EXTRA_ALL})：第1段階480条件と第2段階追加240条件。銘柄・期間・条件群を切り替え、各条件の全場収支を確認できます。
4. [公開会計](公開会計.json)：比較代表の銘柄別期間会計と公開ファイルの指紋。
5. [事前固定](../../work/wave_v74/事前固定.json)・[前半選定](../../work/wave_v74/前半選定.json)・[追加固定](../../work/wave_v74/extension/追記固定.json)・[追加選定](../../work/wave_v74/extension/選定.json)：探索範囲と各段階の実行前に固定した採点、前16だけから選んだ比較代表。
6. [休止と方向の効果分析](../../work/wave_v74/analysis/基準制限と休止の効果分析.json)・[保有継続の追加分析](../../work/wave_v74/analysis/第二段階の保有継続と休止の分析.json)：同じ設定で休止を変えた結果、方向対照、損失の内訳。
7. [全480の独立会計監査](../../work/wave_v74/audit/全480条件の会計と前半選定の独立監査.json)・[追加240と再利用48の独立会計監査](../../work/wave_v74/audit/純トレール追加240と再利用48の独立監査.json)・[人工経路](../../work/wave_v74/audit/人工経路と未来切断の独立監査.json)・[実経路の未来切断](../../work/wave_v74/audit/保存実経路の未来切断と改変監査.json)・[表示検査](../../work/wave_v74/review/HTML表示の独立検査.json)。

## 金額の読み方

- 利益：手数料後に黒字となった全決済取引の金額合計。
- 損失：手数料後に赤字となった全決済取引の損失絶対額合計。
- 収支：利益−損失。手数料をさらに引く必要はありません。
- 金額損失割合：損失÷（利益＋損失）。50%未満で合計黒字。無取引では未定義です。
- 平均利益／損失：1回の平均勝ち額÷1回の平均負け額。総利益／総損失とは別です。

TOPIXミニ10枚とNK225マイクロ20枚を別々に計算します。円金額を商品間で足した順位付けはしません。枚数・勝率は補助情報です。全返済なので、負け玉を残したまま利益玉だけを集計することはありません。

## 比較した範囲

保存データは2026-09-21デイ〜2026-10-09デイ、29場です。第1段階は主案288条件と対照192条件を固定して再生しました。第2段階は新規方向だけを制限する未検証の休止組合せ240条件を追加固定して再生しました。既存の休止なし48条件と合わせた288条件から別の代表を選びます。最初の480結果・選定は変更していません。

各段階は前16の金額損失割合で基準別の代表を選び、後13では差し替えていません。第2段階は第1段階の結果を閲覧してからの仕様切り分けです。また、元々過去に閲覧・探索したデータの時間分割なので、未知の将来データでの証明ではありません。各3代表は利益の有望候補を意味しません。

主案は始値／前保存場／両者一致の方向制限、即時の新規判断／新規トレール、待機帯0／±0.025%、出口幅0.05／0.1／0.2／0.4%、休止6方式です。休止はなし、2連敗で10分／30分／収束待ち／10分かつ収束、3連敗で30分。損切りと返済トレールは同じ幅です。通常の再入場待ちは30秒、保有期限は60分。ATRは使いません。

収束は、許可方向への逆行極値が30秒更新されず、始値0.025%の反発があり、30秒前に比べて売買両気配も許可方向へ1呼値進んだ場合です。参加者の感情を直接観測した判定ではありません。

## データ・約定・限界

始値は当該セッションの時刻を持つOpeningPriceを使用し、古い値の場合は最初に観測したCurrentPriceを使います。「前終値」は直前の保存セッションの最終新鮮価格です。公式終値・日次PreviousCloseとは区別します。最初の保存場には前値がなく、補完しません。[参照値の由来](../../work/wave_v74/inputs/refmetadata.json)に全58口座を保存しています。

判断した原本行の次の有効気配で、買いはask、売りはbidに仮想約定します。判断用・約定用ともラージ板の代理です。実際のミニ／マイクロの気配、注文待ち、深さ、通信遅延は再現していません。板時計はCurrentPriceTimeの代理時計です。同じ観測の将来高安で有利な約定を選んではいません。

片道1枚の立会手数料はTOPIXミニ41.8円、NK225マイクロ11円です。新規・返済の各注文で合計料金の1円未満を切り捨てます。気配差は実際に用いた売買価格に含まれます。気配差の影響を示す中値置換は同じ約定行の価格だけの比較であり、入口・出口を中値で再計算した成績ではありません。

場内返済の判断はデイ15:34／ナイト05:49からです。欠損時には次の有効気配まで約定が遅れます。保存列の末尾を知って強制清算する処理はなく、途中で未来を切った再生には建玉が残り得ます。全29場の完了再生について別途全返済を監査しています。

原本book/candleは読み取り専用、現在セッションAPI取得0、実注文0です。第1段階の結果を見て第2段階240条件を追加したことを明示し、結果・代表は別保存しています。各段階で後13の結果を理由に代表を差し替えていません。

## 再現

プロジェクトルートで実行します。初回の事前固定は保存済みで、上書きしません。

```text
python -X utf8 work/wave_v74/study.py --workers 6
python -X utf8 work/wave_v74/study.py --select
python -X utf8 work/wave_v74/extension.py --workers 6
python -X utf8 work/wave_v74/extension.py --select
python -X utf8 work/wave_v74/analysis/diagnose.py
python -X utf8 work/wave_v74/report/generate.py
python -X utf8 work/wave_v74/review/verify.py
python -X utf8 work/wave_v74/review/verify.py --extra
python -X utf8 work/wave_v74/review/verify_all.py
python -X utf8 work/wave_v74/review/verify_all.py --extra
```

保存済み結果がある条件は再生を省略します。計算本体は[engine.py](../../work/wave_v74/engine.py)、設定・会計は[study.py](../../work/wave_v74/study.py)です。実運用の注文プログラムは変更していません。
'''
    (OUT/'README.md').write_text(text,encoding='utf8')


def links(paths: list[Path]) -> int:
    """機能: 案内と公開HTMLのローカル参照先を検査する。

    引数: paths(list[Path])。返り値: 照合リンク数(int)。
    """
    count=0
    for path in paths:
        source=path.read_text(encoding='utf8')
        refs=([t['href'] for t in BeautifulSoup(source,'html.parser').select('a[href]')]
              if path.suffix=='.html' else re.findall(r'\]\(([^)]+)\)',source))
        for href in refs:
            if href.startswith(('http:','https:','#')):
                continue
            target=path.parent/unquote(href.split('#',1)[0].split('?',1)[0])
            assert target.exists(),(path,href)
            count+=1
    return count


def main() -> None:
    """機能: 監査・表示確認済みの作業を最新として索引へ登録する。

    引数: なし。返り値: なし(None)。過去の作業フォルダは書き換えない。
    """
    audit=read(HERE/'audit/全480条件の会計と前半選定の独立監査.json')
    extra_audit=read(HERE/'audit/純トレール追加240と再利用48の独立監査.json')
    review=read(HERE/'review/HTML表示の独立検査.json')
    assert audit['合格'] and audit['口座会計数']==480*58
    assert extra_audit['合格'] and extra_audit['追加条件数']==240 and extra_audit['口座会計数']==288*58
    assert review['全合格'] and review['目視確認']
    assert hashlib.sha256((OUT/MAIN).read_bytes()).hexdigest()==review['HTML_SHA256']
    for name,proof_name in ((EXTRA,'追加_HTML表示の独立検査.json'),(ALL,'全一覧表示の独立検査.json'),(EXTRA_ALL,'追加一覧表示の独立検査.json')):
        proof=read(HERE/'review'/proof_name)
        assert proof['全合格'] and proof['目視確認']
        assert hashlib.sha256((OUT/name).read_bytes()).hexdigest()==proof['HTML_SHA256']
    documents()
    folder=OUT.name
    index=ROOT/'アルゴリズム調査/index.html'
    readme=ROOT/'アルゴリズム調査/README.md'
    source=index.read_text(encoding='utf8').replace('class="task latest"','class="task"').replace(' <span class="badge">最新</span>','')
    source=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00070：始値・前保存場の方向制限と連敗休止。480＋追加240条件、全29セッション、銘柄別の利益・損失・収支と金額損失割合。</p>',source,count=1,flags=re.S)
    block=f'''<!--00070開始--><article class="task latest"><div class="number">作業00070 <span class="badge">最新</span></div><h2>始値と前終値の方向制限と連敗休止</h2><p>基準より上は買い、下は売り。追跡幅と連敗後の時間・収束休止を第1段階480＋追加240条件で比較。新規だけの方向制限も切り分け、全29場・週の金額損益と五分足売買図を掲載。</p><a class="button" href="{folder}/{MAIN}">説明と全セッション損益を開く →</a><p><a href="{folder}/{EXTRA}">新規方向だけ制限する追加検証</a> · <a href="{folder}/{ALL}">第1段階480条件</a> · <a href="{folder}/{EXTRA_ALL}">追加240条件</a> · <a href="{folder}/README.md">資料案内</a> · <a href="{folder}/公開会計.json">公開会計</a></p></article><!--00070終了-->'''
    if '<!--00070開始-->' in source:
        source=re.sub(r'<!--00070開始-->.*?<!--00070終了-->',block,source,flags=re.S)
    else:
        assert '<!--00069開始-->' in source
        source=source.replace('<!--00069開始-->',block+'\n<!--00069開始-->',1)
    # ----------------------------------------
    # 旧作業のリンクを維持し、最新表示だけを今回へ移す。
    text=readme.read_text(encoding='utf8').replace('**最新は00069','**00069')
    guide=f'''<!--00070案内開始-->
**最新は00070の[基準価格と連敗休止の説明と全セッション損益]({folder}/{MAIN})。始値・前保存場・両者一致、連敗休止と収束再開を480＋追加240条件で比較。TOPIXミニ10枚／NK225マイクロ20枚、全29場、銘柄別の金額損失割合。**

[新規方向だけ制限する追加検証]({folder}/{EXTRA}) · [全480条件]({folder}/{ALL}) · [追加240条件]({folder}/{EXTRA_ALL}) · [資料案内]({folder}/README.md) · [公開会計]({folder}/公開会計.json)。
<!--00070案内終了-->
'''
    if '<!--00070案内開始-->' in text:
        text=re.sub(r'<!--00070案内開始-->.*?<!--00070案内終了-->\n?',guide,text,flags=re.S)
    else:
        assert '<!--00069案内開始-->' in text
        text=text.replace('<!--00069案内開始-->',guide+'\n<!--00069案内開始-->',1)
    index.write_text(source,encoding='utf8')
    readme.write_text(text,encoding='utf8')
    count=links([index,readme,OUT/MAIN,OUT/ALL,OUT/EXTRA,OUT/EXTRA_ALL,OUT/'README.md'])
    (HERE/'公開リンク照合.json').write_text(json.dumps(dict(合格=True,照合リンク数=count,最新='00070'),ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(合格=True,照合リンク数=count),ensure_ascii=False))


if __name__=='__main__':
    main()

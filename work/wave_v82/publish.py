"""反転検証の会計・読む順序・調査一覧を今回の番号へ公開する。"""

from pathlib import Path
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FOLDER = '00078_安定赤字手法の売買反転検証'
PUBLIC = ROOT / 'アルゴリズム調査' / FOLDER
MAIN = '安定して負ける手法の反転と全セッション損益.html'
ALL = '全188条件の前半反転比較.html'


def read(path: Path) -> object:
    """機能: 公開する保存結果を読み取る。

    引数: path(Path)。返り値: 内容(object)。
    """
    return json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 今回と旧資料の内容を確認する。

    引数: path(Path)。返り値: SHA-256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    """機能: 今回の公開フォルダへJSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(PUBLIC)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def main() -> None:
    """機能: 新しいHTMLの案内と検算資料を揃え、旧成果を保持する。

    引数: なし。返り値: なし(None)。HTML・監査完了後に使用する。
    """
    assert (PUBLIC/MAIN).exists() and (PUBLIC/ALL).exists()
    research = ROOT / 'アルゴリズム調査'
    old = research / '00077_保有時間を決めない二市場方向追従'
    old_hashes = read(old/'公開指紋.json')['成果']
    preserved = {str((old/n).relative_to(research)):old_hashes[n] for n in
        ('時間で区切らない方向追従と全セッション損益.html','全条件の前半比較.html','README.md')}
    assert all(digest(research/n)==h for n,h in preserved.items())
    assert old_hashes['時間で区切らない方向追従と全セッション損益.html']=='fa868c3a233fe9a94a797f19e0d14fb7447594cceed6c0a4787bcbc320e00e7d'
    fixed=read(HERE/'事前固定.json'); data=read(HERE/'report/描画資料.json')
    audits={str(p.relative_to(HERE/'audit')):read(p) for p in sorted((HERE/'audit').rglob('*.json'))}
    save(PUBLIC/'公開会計.json',dict(期間=fixed['全30'], 前半=fixed['前16'], 後半=fixed['後14'],
        元と反転=data['final'], 相場別=data['regimes'], 相手鮮度3秒=data['strict'], 監査=audits,
        会計='TOPIXミニ10枚とNK225マイクロ20枚を別々に評価。損益は決済組ごとの手数料後。全建玉を場内返済し、無取引を勝ちに数えない。'))
    save(PUBLIC/'検証条件と固定記録.json',dict(事前固定=fixed, 元前半順位=read(HERE/'元前半の選定順位.json'),
        相場分類=read(HERE/'diagnosis/相場分類.json'), 旧成果保持=preserved,
        制約='既知30場であり未知検証ではない。真の受信時計なし、ラージ気配による小型商品代用。Cは元成行の前半から反転余地を計算して選んだ探索。'))
    rows=['| 選定枠 | TOPIX 元 → 反転 | 日経 元 → 反転 |','| --- | ---: | ---: |']
    for pair in fixed['pairs']:
        a=data['final']['5'][pair['original']['id']]['periods']['対象']
        b=data['final']['5'][pair['reverse']['id']]['periods']['対象']
        rows.append(f'| {pair["label"]}：{pair["name"]} | {a["TOPIX"]["net"]:+,.0f} → {b["TOPIX"]["net"]:+,.0f}円 | {a["NK225"]["net"]:+,.0f} → {b["NK225"]["net"]:+,.0f}円 |')
    (PUBLIC/'README.md').write_text(f'''# 00078：安定赤字手法の売買反転検証

最初に **[{MAIN}]({MAIN})** を開いてください。

1. [{MAIN}]({MAIN})：結論、選定3枠、元と反転の全30場損益、上昇・下落・横ばい別の結果。
2. [{ALL}]({ALL})：元188条件と反転188条件の前16比較。単独対照8は代表選定から除外。
3. [公開会計.json](公開会計.json)：固定3ペアの0/1/5秒会計・相場分類・独立監査。
4. [検証条件と固定記録.json](検証条件と固定記録.json)：入力・実装・順位・代表の固定記録。

元と同時刻・同数量で成行約定する場合は、反転収支＝−元収支−2×（売買気配差の負担＋手数料）です。費用は売買を逆にしても利益には変わりません。上限付き新規は約定・不成立が変わるため、この式で代用せず注文から再生しました。

以下は全30場、発注待ち5秒、立会手数料込み。TOPIXミニ10枚、日経マイクロ20枚です。

{chr(10).join(rows)}

Aは元の赤字の安定性、Bは中値方向の外れの安定性、Cは費用を超える反転余地で前16から選びました。Cの選択には元成行の前半台帳から計算できる反転余地を使うため、前半探索です。代表を固定してから後14を再生し、その結果では選び直していません。全30は以前の調査でも既知なので、未知期間の成績とは呼びません。

通常の保有期限・固定利確・固定損切り・取引再開までの固定休止は設けません。入口と出口の方向を同時に反転し、セッション終了前は全返済します。注文待ちは5秒経過後の最初の有効観測で約定するため、5秒以内の実約定を保証するモデルではありません。板はラージ、時計は最終約定時刻の代理で、実受信時計や小型商品の板・注文順位は未再現です。現在API取得・実注文は0です。

上昇・下落・横ばいは収録区間の始終中値の変化率±0.1%による事後分類です。途中の一方向性を意味せず、売買条件や代表の選択にも使いません。

## 再現資料

- [再生プログラム](../../work/wave_v82/research.py)、[元前半の選定順位](../../work/wave_v82/元前半の選定順位.json)。
- [診断資料](../../work/wave_v82/diagnosis/)、[独立監査](../../work/wave_v82/audit/)、[HTML生成](../../work/wave_v82/report/generate.py)。

プロジェクトルートから実行します。入力・コードの指紋を照合し、既存結果は再利用します。

```text
python -X utf8 work/wave_v82/research.py --workers 3
python -X utf8 work/wave_v82/research.py --final --workers 3
python -X utf8 work/wave_v82/research.py --quality --workers 3
python -X utf8 work/wave_v82/report/generate.py
python -X utf8 work/wave_v82/publish.py
```

条件を変える場合は新しい作業へ保存し、既存結果を上書きしないでください。
''',encoding='utf8')
    # ----------------------------------------
    index=research/'index.html'; body=index.read_text(encoding='utf8')
    body=re.sub(r'<!--00078開始-->.*?<!--00078終了-->\s*','',body,flags=re.S)
    body=body.replace('class="task latest"','class="task"').replace('<span class="badge">最新</span>','')
    block=f'''<!--00078開始--><article class="task latest"><div class="number">作業00078 <span class="badge">最新</span></div><h2>安定赤字手法の売買反転検証</h2><p>毎場の赤字と価格方向の外れを分け、元188条件を売買反転。前半で固定した3ペアの全30場、費用と相場方向別を比較。</p><a class="button" href="{FOLDER}/{MAIN}">元と反転の全セッション損益を開く →</a><p><a href="{FOLDER}/{ALL}">全188条件の前半反転比較</a> · <a href="{FOLDER}/README.md">読む順序</a></p></article><!--00078終了-->'''
    body=body.replace('<!--00077開始-->',block+'\n<!--00077開始-->',1)
    body=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00078：安定して赤字になる手法を売買反転し、費用込みで再生。全30場の元と反転、上昇・下落・横ばい別を比較。</p>',body,count=1,flags=re.S)
    body=re.sub(r'<footer>.*?</footer>','<footer>最新作業は00078です。次の作業は00079以降へ追加します。</footer>',body,count=1,flags=re.S)
    index.write_text(body,encoding='utf8')
    listing=research/'README.md'; body=listing.read_text(encoding='utf8')
    body=re.sub(r'<!--00078案内開始-->.*?<!--00078案内終了-->\s*','',body,flags=re.S).replace('**最新は00077の','**00077の')
    head,rest=body.split('\n',1)
    intro=f'''\n\n<!--00078案内開始-->
**最新は00078の[{MAIN}]({FOLDER}/{MAIN})。安定赤字の元188条件を反転し、固定3ペアの全30場で確認。方向の外れと費用を分けて検証。**

[{ALL}]({FOLDER}/{ALL}) · [読む順序]({FOLDER}/README.md) · [公開会計]({FOLDER}/公開会計.json)。
<!--00078案内終了-->\n'''
    listing.write_text(head+intro+rest,encoding='utf8')
    path=ROOT/'README.md'; body=path.read_text(encoding='utf8')
    body=re.sub(r'最新の調査は .*?(?=\n\n)',f'最新の調査は **[00078：安定赤字手法の売買反転検証](アルゴリズム調査/{FOLDER}/{MAIN})** です。[資料案内と読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。毎場赤字と価格方向の外れを分けて元188条件を反転し、固定3ペアの全30場・発注待ち0/1/5秒を確認しました。',body,count=1)
    path.write_text(body,encoding='utf8')
    save(PUBLIC/'公開指紋.json',dict(成果={p.name:digest(p) for p in sorted(PUBLIC.iterdir()) if p.is_file() and p.name!='公開指紋.json'},旧成果保持=preserved))
    print('00078の公開資料と三つの入口を更新しました。')


if __name__=='__main__':
    main()

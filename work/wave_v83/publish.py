"""今回の検証結果と再現資料を新番号へ公開する。"""
from pathlib import Path
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / 'アルゴリズム調査'
FOLDER = '00079_方向予測を使わない注文手法の検証'
PUBLIC = RESEARCH / FOLDER
MAIN = '予測を使わない注文手法と全セッション損益.html'
FAMILIES = '家族別12手法の説明と全セッション損益.html'
COMPARISON = '全288条件の前半比較.html'


def read(path):
    """
    機能: 固定済み成果をJSONとして読む。
    引数: path(Path)。
    返り値: object。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    """
    機能: 公開ファイルと旧成果の指紋を算出する。
    引数: path(Path)。
    返り値: str のSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    """
    機能: 今回の公開領域だけに検証資料を保存する。
    引数: path(Path)、value(object)。
    返り値: None。
    """
    assert path.resolve().is_relative_to(PUBLIC.resolve())
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def main():
    """
    機能: 旧成果を保持し、今回のHTML・会計・入口を公開する。
    引数: なし。
    返り値: None。
    """
    for name in (MAIN, FAMILIES, COMPARISON):
        assert (PUBLIC / name).exists(), name
    old = RESEARCH / '00078_安定赤字手法の売買反転検証'
    old_hashes = read(old / '公開指紋.json')['成果']
    preserved = {str((old / name).relative_to(RESEARCH)): old_hashes[name] for name in
                 ('安定して負ける手法の反転と全セッション損益.html', '全188条件の前半反転比較.html', 'README.md')}
    assert all(digest(RESEARCH / name) == expected for name, expected in preserved.items())
    fixed = read(HERE / 'results/事前固定.json')
    selected = read(HERE / '前半選定.json')
    final = {name: read(HERE / 'final/delay0/results' / (name + '.json')) for name in selected['selected']}
    ideal = {name: read(HERE / 'ideal/results' / (name + '.json')) for name in selected['selected']}
    ideal_fee = {name: read(HERE / 'ideal_fee/results' / (name + '.json')) for name in selected['selected']}
    persistent = {path.stem: read(path) for path in (HERE / 'persistent/results').glob('*.json')}
    audits = {str(path.relative_to(HERE / 'audit')): read(path) for path in sorted((HERE / 'audit').glob('*.json'))}
    save(PUBLIC / '公開会計.json', dict(期間=fixed['全30'], 通常=final, 論理対照=ideal,
         指定現在値約定と実手数料=ideal_fee, 指値保持モデル=persistent,
         無作為20種=read(HERE / 'sensitivity/無作為20種の比較.json'), 監査=audits,
         表示検査=read(HERE / 'report/HTML表示の独立検査.json'),
         会計='主評価は全玉終了までの親組損益。決済脚の総利益・総損失も別保存し、どちらの総収支も一致。遅延なしの当該気配約定、手数料込み。'))
    save(PUBLIC / '検証条件と固定記録.json', dict(事前固定=fixed, 前半選定=selected,
         入力照合=read(HERE / 'prepared/価格入力の照合.json'), 論理対照=read(HERE / 'ideal/固定条件.json'),
         指定現在値と実手数料=read(HERE / 'ideal_fee/固定条件.json'), 指値保持改修=read(HERE / 'persistent/固定条件.json'),
         損失診断=read(HERE / 'diagnosis/12家族代表の損失構造.json'), 旧成果保持=preserved))
    save(PUBLIC / '注文手法の論理対照.json', dict(仮説=read(HERE / 'theory/注文管理だけで利益を生む仮説と10家族.json'),
         人工相場=read(HERE / 'theory/人工相場による注文手法の性質.json')))
    table = ['| 選定観点 | 手法 | TOPIXミニ | 日経マイクロ |', '| --- | --- | ---: | ---: |']
    for representative in selected['primary']:
        result = final[representative['id']]
        totals = result['periods']['対象']
        table.append(f'| {representative["criterion"]} | {representative["id"]}：{result["config"]["name"]} | {totals["TOPIX"]["net"]:+,.0f}円 | {totals["NK225"]["net"]:+,.0f}円 |')
    (PUBLIC / 'README.md').write_text(f'''# 00079：方向予測を使わない注文手法の検証

最初に **[{MAIN}]({MAIN})** を開いてください。

1. [{MAIN}]({MAIN})：結論、3つの選定観点、主代表の説明と全30場の損益。
2. [{FAMILIES}]({FAMILIES})：12系統の固定代表、全セッションの利益・損失・収支。
3. [{COMPARISON}]({COMPARISON})：前16場で比較した全288条件。後半の結果で代表を変更しません。
4. [公開会計.json](公開会計.json)：通常会計、費用なし論理対照、無作為20種、独立監査。
5. [検証条件と固定記録.json](検証条件と固定記録.json)：事前条件、入力、選抜、損失原因、旧成果保持。
6. [注文手法の論理対照.json](注文手法の論理対照.json)：価格の型と注文管理の関係を調べた人工相場・理論。

板数量・足・ATR・他市場の方向を使いません。現在値、自分の注文、建玉、実現損益で動かします。価格予測をしなくても、逆指値やグリッドはそれぞれ持続・反発という値動きに依存します。

主条件は発注遅延なし。判断した観測の売買気配で約定し、新規と返済の手数料を含めます。TOPIXミニは片方向最大10枚、日経マイクロは片方向最大20枚。初回・追加・分割の枚数は手法ごとに異なります。残った損失玉も含めセッション末までに全返済します。

以下は全30場の収支です。3つの観点で同じ手法が選ばれることもあり、独立した成功例が3つあるという意味ではありません。

{chr(10).join(table)}

利益・損失の主集計は、全建玉を閉じるまでの親組単位です。脚単位の利確回数や金額割合と区別します。利益割合が違っても、親組と脚の純収支は一致します。無取引を勝ちに含めません。

現在値で必ず約定し、気配差・手数料もゼロにした別の論理対照もあります。注文状態から再生するので、通常成績へ費用を足し戻した数値や将来損益の上界とは異なります。実行可能な約定成績ではありません。

さらに現在値で必ず約定して実手数料を払う中間対照と、主2条件・グリッド1条件の指値を保持する改修を分けて掲載します。改修は全30場の結果を見た後の仮説検証です。変数は選び直しません。対向気配が条件内に入れば元指値で全量約定する代理モデルで、実取引所の待ち順位や部分約定は検証していません。

## 再現と範囲

- [手法カタログ](../../work/wave_v83/catalog.py)、[注文エンジン](../../work/wave_v83/engine.py)、[会計と選抜](../../work/wave_v83/research.py)。
- [原因診断](../../work/wave_v83/diagnosis.py)、[論理対照](../../work/wave_v83/ideal.py)、[独立監査](../../work/wave_v83/audit/)。
- [原本価格の照合](../../work/wave_v83/prepared/価格入力の照合.json)。

```text
python -X utf8 work/wave_v83/research.py --phase train --workers 4
python -X utf8 work/wave_v83/research.py --phase final --workers 4
python -X utf8 work/wave_v83/research.py --phase sensitivity
python -X utf8 work/wave_v83/diagnosis.py
python -X utf8 work/wave_v83/ideal.py
python -X utf8 work/wave_v83/ideal_fee.py
python -X utf8 work/wave_v83/persistent.py
python -X utf8 work/wave_v83/report/build.py
python -X utf8 work/wave_v83/publish.py
```

データは2026-09-21デイ〜2026-10-09ナイトの既知30場です。前16で代表を固定し後14を再点検しましたが、過去にも閲覧した期間なので未知の検証とは呼びません。最終約定時計を受信時刻の代用としており、小型商品の独自気配・注文順位・部分約定は再現していません。気配はラージのものを約定会計だけに使います。現在API取得・実注文は0です。

新規約定で有効になった通常の返済条件は次の観測から監視します。同一観測で無限に再入場しません。指値型は価格条件成立時のIOCであり、板に置いた指値の待ち順位の再現ではありません。時間で通常保有を打ち切らず、場末のみ既知の時計で返済します。

追加の指値保持モデルで待機注文が後続観測の冒頭に約定した場合は、その観測で子の返済条件を1回評価します。主条件の観測末尾における即時新規とは処理順が異なり、どちらも親約定前の価格で子条件を有効にしません。

判断後5秒以内の最悪約定は今回の基礎比較には混ぜていません。5秒後の一点の約定とは別の検証です。
''', encoding='utf-8')
    # ----------------------------------------
    index = RESEARCH / 'index.html'
    body = index.read_text(encoding='utf-8')
    body = re.sub(r'<!--00079開始-->.*?<!--00079終了-->\s*', '', body, flags=re.S)
    body = body.replace('class="task latest"', 'class="task"').replace('<span class="badge">最新</span>', '')
    block = f'''<!--00079開始--><article class="task latest"><div class="number">作業00079 <span class="badge">最新</span></div><h2>方向予測を使わない注文手法の検証</h2><p>IFD・両建て・追尾・グリッド・段階追加の12系統288条件。遅延なしで、全玉会計と費用なし論理対照を比較。</p><a class="primary" href="{FOLDER}/{MAIN}">説明と全セッション損益を開く</a><a href="{FOLDER}/{FAMILIES}">12系統を比較</a><a href="{FOLDER}/{COMPARISON}">全288条件</a><a href="{FOLDER}/README.md">読む順序</a></article><!--00079終了-->\n'''
    marker = re.search(r'<article\s+class="task', body)
    assert marker is not None
    body = body[:marker.start()] + block + body[marker.start():]
    index.write_text(body, encoding='utf-8')
    listing = RESEARCH / 'README.md'
    body = listing.read_text(encoding='utf-8')
    body = re.sub(r'<!--00079案内開始-->.*?<!--00079案内終了-->\s*', '', body, flags=re.S)
    body = body.replace('**最新は00078', '**00078')
    first, rest = body.split('\n', 1)
    listing.write_text(first + f'''\n\n<!--00079案内開始-->
**最新は00079の[{MAIN}]({FOLDER}/{MAIN})。方向予測を使わない12系統288条件を遅延なしで比較。固定代表の全30場と費用なし論理対照を掲載。**

[{FAMILIES}]({FOLDER}/{FAMILIES}) · [{COMPARISON}]({FOLDER}/{COMPARISON}) · [読む順序]({FOLDER}/README.md)。
<!--00079案内終了-->
''' + rest, encoding='utf-8')
    root_readme = ROOT / 'README.md'
    body = root_readme.read_text(encoding='utf-8')
    body = re.sub(r'最新の調査は .*?(?=\n\n)', f'最新の調査は **[00079：方向予測を使わない注文手法の検証](アルゴリズム調査/{FOLDER}/{MAIN})** です。[資料案内と読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。12系統288条件を遅延なしで比較し、固定代表の全30場と費用なしの論理対照を掲載しました。', body, count=1)
    root_readme.write_text(body, encoding='utf-8')
    save(PUBLIC / '公開指紋.json', dict(成果={p.name: digest(p) for p in PUBLIC.iterdir() if p.is_file() and p.name != '公開指紋.json'}, 旧成果保持=preserved))
    print('00079の会計・読む順序・三つの入口を更新しました。')


if __name__ == '__main__':
    main()

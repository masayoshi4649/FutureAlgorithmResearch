"""順行逆指値と反転売買の検証を新しい作業番号へ公開する。"""
from pathlib import Path
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / 'アルゴリズム調査'
FOLDER = '00080_順行逆指値と反転売買の検証'
PUBLIC = RESEARCH / FOLDER
MAIN = '順行逆指値とドテンの説明と全セッション損益.html'
COMPARISON = '全108条件の前半比較.html'


def read(path):
    """
    機能: 検算済みの日本語JSONを読む。
    引数: path(Path)。
    返り値: object。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    """
    機能: 成果と再現資料のSHA256を求める。
    引数: path(Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    """
    機能: 今回の公開領域へ有限数値のJSONを書き込む。
    引数: path(Path)、value(object)。
    返り値: None。
    """
    assert path.resolve().is_relative_to(PUBLIC.resolve())
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def main():
    """
    機能: 全セッション会計・固定記録・読む順序を公開し、一覧を更新する。
    引数: なし。
    返り値: None。旧作業の資料は保持する。
    """
    for name in (MAIN, COMPARISON):
        assert (PUBLIC / name).exists(), name
    old = RESEARCH / '00079_方向予測を使わない注文手法の検証'
    previous = read(old / '公開指紋.json')['成果']
    preserved = {str((old / name).relative_to(RESEARCH)): expected for name, expected in previous.items()}
    assert all(digest(RESEARCH / name) == expected for name, expected in preserved.items())
    fixed = read(HERE / 'results/事前固定.json')
    selected = read(HERE / '前半選定.json')
    normal = {name: read(HERE / 'final/delay0/results' / (name + '.json')) for name in selected['selected']}
    ideal = {name: read(HERE / 'ideal_fee/results' / (name + '.json')) for name in selected['selected']}
    supplemental = {phase: {p.stem: read(p) for p in (HERE / 'supplement' / phase / 'results').glob('*.json')}
                    for phase in ('final', 'ideal_fee')}
    audits = {p.name: read(p) for p in sorted((HERE / 'audit').glob('*.json'))}
    diagnosis = {str(p.relative_to(HERE)): read(p) for parent in ('analysis', 'diagnosis')
                 for p in sorted((HERE / parent).glob('*.json'))}
    report_checks = {p.name: read(p) for p in sorted((HERE / 'report').glob('*.json'))
                     if any(word in p.name for word in ('検査', '監査', '検証'))}
    save(PUBLIC / '公開会計.json', dict(全30=fixed['全30'], 通常気配=normal,
         現在値必約定と実手数料=ideal, 少数取引の探索的参考=supplemental,
         独立監査=audits, 表示検査=report_checks,
         会計='1回の新規と全返済を1取引として新規・返済の両手数料を含める。ドテンは返済と反対新規の別注文。全残玉を各場末に清算。'))
    save(PUBLIC / '検証条件と固定記録.json', dict(事前固定=fixed, 前半選定=selected,
         現在値必約定の条件=read(HERE / 'ideal_fee/固定条件.json'),
         探索的参考の追加固定=read(HERE / 'supplement/追加固定.json'),
         入力照合=read(HERE.parent / 'wave_v83/prepared/価格入力の照合.json'),
         損失診断=diagnosis, 旧成果保持=preserved))
    # ----------------------------------------
    table = ['| 同幅で比較した手法 | TOPIXミニ10枚 | 日経マイクロ20枚 |', '| --- | ---: | ---: |']
    for item in selected['common_width']:
        result = ideal[item['id']]
        totals = result['periods']['対象']
        table.append(f'| {item["id"]}：{result["config"]["name"]} | {totals["TOPIX"]["net"]:+,.0f}円 | {totals["NK225"]["net"]:+,.0f}円 |')
    (PUBLIC / 'README.md').write_text(f'''# 00080：順行逆指値と反転売買の検証

最初に **[{MAIN}]({MAIN})** を開いてください。

1. [{MAIN}]({MAIN})：短い結論、売買図、同幅6手法の比較、各手法の全30セッション損益。
2. [{COMPARISON}]({COMPARISON})：前16セッションで検証した6系統108条件。
3. [公開会計.json](公開会計.json)：全固定代表と少数取引の参考、通常約定・現在値必約定の会計、独立監査。
4. [検証条件と固定記録.json](検証条件と固定記録.json)：事前条件、選定、損失診断、入力と旧成果の指紋。

方法は「一定幅上がったら買い、下がったら売り、最高値・最安値から一定幅戻したら返済」です。返済後の即ドテン、もう一段の確認、利益時だけドテン、普通の待機を比べました。入口方向だけを逆張りへ変えた固定損切り・固定利確も対照にしています。

板数量・足・ATR・他市場の方向は使いません。現在値と自分の建玉・注文・確定損益だけで判断します。「止まった」は一定幅の戻りで定義し、通常の時間制限はありません。場末だけ全返済します。

以下は**現在値で必ず約定し、実手数料を払う仮定**の全30セッション収支です。入口幅・出口幅はどれもTOPIX4ポイント、日経80ポイント。実際にこの価格で全量約定できるという意味ではありません。

{chr(10).join(table)}

即ドテンは両銘柄とも手数料を引く前から赤字でした。順行化が逆張り対照を上回ったのは日経で、TOPIXは逆でした。同じ固定代表を当該観測の売買気配で約定した会計もHTMLで切り替えられます。二つは注文状態から再生し直した別モデルであり、差額を単純な費用額とは解釈しません。

より広い入口の固定利確型 F1_W32_V0 は、現在値必約定＋手数料でTOPIX+37,364円、日経+190,080円でした。ただし黒字は両商品とも30場中14場で、売買気配のモデルではTOPIX−52,636円、日経+158,080円です。両商品で安定して利益が出ると確認した条件ではありません。

前16の最低取引数を満たす候補から、3つの観点と各系統の代表を固定しました。これは推奨候補という意味ではありません。特に1取引当たりの効率の選定は、取引数の多い赤字手法が選ばれ得るため、全体収支を併記しています。主代表・系統代表・損益で選ばない同幅6条件の重複を除き14条件を後14で再点検しました。

前16で唯一両銘柄黒字だった広幅の即ドテンは各10取引と少数でした。主14を見た後に、その1条件を前16だけの基準で追加固定して検証した結果も、探索的参考として別掲載しました。主選定は変更していません。

## 再現資料

- [手法と幅](../../work/wave_v84/catalog.py)、[注文エンジン](../../work/wave_v84/engine.py)、[会計と選定](../../work/wave_v84/research.py)。
- [少数取引の参考](../../work/wave_v84/supplement.py)、[独立監査](../../work/wave_v84/audit/)。
- 生データは読取専用で、[前作業で照合した価格入力](../../work/wave_v83/prepared/価格入力の照合.json)を再利用。

```text
python -X utf8 work/wave_v84/research.py --phase train --workers 4
python -X utf8 work/wave_v84/research.py --phase final --workers 4
python -X utf8 work/wave_v84/research.py --phase ideal_fee --workers 4
python -X utf8 work/wave_v84/supplement.py
python -X utf8 work/wave_v84/report/build.py
python -X utf8 work/wave_v84/publish.py
```

対象は2026年9月21日デイ〜10月9日ナイトの既知30セッションです。前16で選び後14で再点検していますが、過去にも見た期間であり、未知データでの証明ではありません。最終約定時刻を観測時計の代用とし、ラージの気配を小型商品へ代用しています。待ち順位・部分約定は再現していません。

新規はTOPIXミニ10枚又は日経マイクロ20枚。同時に1方向のみ保有し、返済できるまで反対の新規は行いません。手数料は片道1枚TOPIX41.8円、日経11円で注文合計の円未満切捨てです。

固定追加遅延は0です。気配欠測時の有効観測待ちや、予定時刻と次の観測との差は残ります。判断後5秒以内の最悪約定は今回の論理比較に含めていません。現在API取得・実注文は0です。
''', encoding='utf-8')
    # ----------------------------------------
    index = RESEARCH / 'index.html'
    body = index.read_text(encoding='utf-8')
    body = re.sub(r'<!--00080開始-->.*?<!--00080終了-->\s*', '', body, flags=re.S)
    body = body.replace('class="task latest"', 'class="task"').replace('<span class="badge">最新</span>', '')
    block = f'''<!--00080開始--><article class="task latest"><div class="number">作業00080 <span class="badge">最新</span></div><h2>順行逆指値と反転売買の検証</h2><p>上がれば買い、下がれば売り、戻したら返済・ドテン。6系統108条件を遅延なしで比較し、同じ幅での違いと全セッション損益を掲載。</p><a class="primary" href="{FOLDER}/{MAIN}">説明と全セッション損益を開く</a><a href="{FOLDER}/{COMPARISON}">全108条件</a><a href="{FOLDER}/README.md">読む順序</a></article><!--00080終了-->\n'''
    marker = re.search(r'<article\s+class="task', body)
    assert marker is not None
    body = body[:marker.start()] + block + body[marker.start():]
    index.write_text(body, encoding='utf-8')
    listing = RESEARCH / 'README.md'
    body = listing.read_text(encoding='utf-8')
    body = re.sub(r'<!--00080案内開始-->.*?<!--00080案内終了-->\s*', '', body, flags=re.S)
    body = body.replace('**最新は00079', '**00079')
    first, rest = body.split('\n', 1)
    listing.write_text(first + f'''\n\n<!--00080案内開始-->
**最新は00080の[{MAIN}]({FOLDER}/{MAIN})。順行逆指値と反転売買を6系統108条件で比較。固定代表の全30セッションと現在値必約定の対照を掲載。**

[{COMPARISON}]({FOLDER}/{COMPARISON}) · [読む順序]({FOLDER}/README.md)。
<!--00080案内終了-->
''' + rest, encoding='utf-8')
    root_readme = ROOT / 'README.md'
    body = root_readme.read_text(encoding='utf-8')
    body = re.sub(r'最新の調査は .*?(?=\n\n)', f'最新の調査は **[00080：順行逆指値と反転売買の検証](アルゴリズム調査/{FOLDER}/{MAIN})** です。[読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。6系統108条件を比較し、同幅の比較と各代表の全30セッション損益を掲載しました。', body, count=1)
    root_readme.write_text(body, encoding='utf-8')
    save(PUBLIC / '公開指紋.json', dict(成果={p.name: digest(p) for p in PUBLIC.iterdir()
         if p.is_file() and p.name != '公開指紋.json'}, 旧成果保持=preserved))
    print('00080の会計・読む順序・三つの入口を更新しました。')


if __name__ == '__main__':
    main()

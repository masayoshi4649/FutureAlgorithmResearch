"""保有時間を決めない方向追従の公開資料と入口案内を保存する。"""

from pathlib import Path
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FOLDER = '00077_保有時間を決めない二市場方向追従'
PUBLIC = ROOT / 'アルゴリズム調査' / FOLDER
MAIN = '時間で区切らない方向追従と全セッション損益.html'
ALL = '全条件の前半比較.html'


def read(path: Path) -> object:
    """機能: 公開対象の保存結果を読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: ファイルが保持されていることを確認する。

    引数: path(Path)。返り値: SHA-256文字列(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    """機能: 今回の公開フォルダへ結果JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(PUBLIC)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def main() -> None:
    """機能: 過去成果を保持し、新しい資料案内と入口を更新する。

    引数: なし。返り値: なし(None)。公開HTMLと全会計が揃ってから使用する。
    """
    assert (PUBLIC / MAIN).exists() and (PUBLIC / ALL).exists()
    oldfolder = '00076_5秒発注遅延を含む秒スキャルピング/'
    preserved = {
        oldfolder + '秒スキャルピングの改善と全セッション損益.html': '9822178592bbbc63d3c8dca9da2da72b8de46be482cd5683e25d0f4193aa55cc',
        oldfolder + '全330条件の前半比較.html': '6367c8b32d99f5873ab421d628322a7fc720d23c4aca17ea8a21dd922090101c',
        oldfolder + 'README.md': '80194d899e4e3e3e3f7ac04c17d0fc0e56b4169ff6062cb3bc9c8efef738794e',
    }
    assert all(digest(ROOT / 'アルゴリズム調査' / n) == h for n, h in preserved.items())
    data = read(HERE / 'report/描画資料.json')
    initial = read(HERE / '初回事前固定.json')
    repairs = read(HERE / '改修前固定.json')
    selected = read(HERE / '前半選定.json')
    audits = {str(p.relative_to(HERE / 'audit')): read(p) for p in sorted((HERE / 'audit').rglob('*.json'))}
    save(PUBLIC / '公開会計.json', dict(期間=initial['全30'], 前半=initial['前16'], 後半=initial['後14'],
        会計='TOPIXミニ10枚とNK225マイクロ20枚を別々に評価。決済組の立会手数料後利益/損失を合計し、無取引を勝ちにしない。',
        遅延別=data['final'], 相手鮮度3秒={p.stem:read(p) for p in sorted((HERE / 'quality3/results').glob('*.json'))},
        監査=audits))
    save(PUBLIC / '検証条件と固定記録.json', dict(初回=initial, 改修=repairs, 選定=selected,
        方向22=read(HERE / 'extended/metadata.json'), 旧成果保持=preserved,
        品質修正の記録='計算開始後・損益未閲覧で状態消去の欠陥を訂正。旧コードと部分成果はwork/wave_v81/prequalityfixへ保存。',
        注意='後14も既知期間。受信時計なし、最終約定時刻を代理使用。ラージ気配で小型商品を代用。未知期間・真の秒単位約定の実証ではない。'))
    table = ['| 再選定した方向 | TOPIXミニ10枚の全30場収支 | NK225マイクロ20枚の全30場収支 |', '| --- | ---: | ---: |']
    for c in selected['改修']:
        a = data['final']['5'][c['id']]['periods']['対象']
        table.append(f'| {c["id"]} | {a["TOPIX"]["net"]:+,.0f}円 | {a["NK225"]["net"]:+,.0f}円 |')
    body = f'''# 00077：保有時間を決めない二市場方向追従

最初に **[{MAIN}]({MAIN})** を開いてください。

1. [{MAIN}]({MAIN})：方向で入る・続ける・降りる条件、損失原因と改修、全30セッションの利益・損失・収支。
2. [{ALL}]({ALL})：初回86＋原因に対応する追加102条件の前16比較。
3. [公開会計.json](公開会計.json)：固定代表の全場・注文待ち0/1/5秒・鮮度感度と独立監査。
4. [検証条件と固定記録.json](検証条件と固定記録.json)：条件・選択基準・コード・入力の固定指紋。

通常の売買は固定利確・固定損切り・保有期限で区切らず、取引再開までの固定休止も設けません。価格の反転幅、板更新イベントの圧力、両者の一致から方向を逐次判断します。共同支持の消失、一市場の反対、両市場の反対一致という3種類の出口を比較します。両市場の反対一致を待つ方式では、中立や片方だけの反対でも保有を続けます。セッション終了前の全返済だけは時刻で行います。

注文5秒待ちの結果です。5秒後に必ず約定する仮定ではなく、5秒経過後の最初の有効観測で約定するため観測待ちが加わります。

{chr(10).join(table)}

利益・損失は各決済組の手数料後金額です。買いは売気配、売りは買気配を使い、手数料とは別に気配差を負担します。データはラージの板で、ミニ・マイクロ自身の板や真の受信時計がないため実運用の秒単位成績ではありません。前16で選択し後14を固定確認しましたが、後14も過去調査で既知です。最新API取得・実注文は0です。

## 再現資料

- [方向定義](../../work/wave_v81/design/方向仕様.json)・[追加9方向](../../work/wave_v81/extended/metadata.json)。
- [初回の損失診断](../../work/wave_v81/diagnosis/初回3代表の方向継続と損失原因.json)・[再生エンジン](../../work/wave_v81/engine.py)・[改修と確認](../../work/wave_v81/pdca.py)。
- [監査資料](../../work/wave_v81/audit/)・[HTML生成](../../work/wave_v81/report/generate.py)。

プロジェクトルートから実行します。保存済み結果は再利用し、入力・実装指紋が変わっていれば停止します。

```text
python -X utf8 work/wave_v81/pdca.py --final --workers 3
python -X utf8 work/wave_v81/pdca.py --quality --workers 3
python -X utf8 work/wave_v81/report/generate.py
python -X utf8 work/wave_v81/publish.py
```

条件を変更する際は既存の成果へ上書きせず、新しい作業として検証してください。
'''
    (PUBLIC / 'README.md').write_text(body, encoding='utf8')
    # ----------------------------------------
    research = ROOT / 'アルゴリズム調査'
    index = research / 'index.html'
    body = index.read_text(encoding='utf8')
    block = f'''<!--00077開始--><article class="task latest"><div class="number">作業00077 <span class="badge">最新</span></div><h2>保有時間を決めない二市場方向追従</h2><p>時間で手仕舞わず、方向の成立・変化で発注。初回86と損失診断に対応した102条件、固定代表の全30場を掲載。</p><a class="button" href="{FOLDER}/{MAIN}">説明と全セッション損益を開く →</a><p><a href="{FOLDER}/{ALL}">全188条件の前半比較</a> · <a href="{FOLDER}/README.md">読む順序</a></p></article><!--00077終了-->'''
    body = re.sub(r'<!--00077開始-->.*?<!--00077終了-->\s*', '', body, flags=re.S)
    body = body.replace('class="task latest"', 'class="task"').replace('<span class="badge">最新</span>', '')
    body = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新00077：保有時間を決めず、二市場の方向で入る・続ける・降りる188条件。損失診断と改修、全30場を掲載。</p>', body, count=1, flags=re.S)
    body = body.replace('<!--00076開始-->', block + '\n<!--00076開始-->', 1)
    body = re.sub(r'<footer>.*?</footer>', '<footer>最新作業は00077です。次の作業は00078以降へ追加します。</footer>', body, count=1, flags=re.S)
    index.write_text(body, encoding='utf8')
    listing = research / 'README.md'
    body = listing.read_text(encoding='utf8')
    body = re.sub(r'<!--00077案内開始-->.*?<!--00077案内終了-->\s*', '', body, flags=re.S)
    body = body.replace('**最新は00076の', '**00076の')
    head, rest = body.split('\n', 1)
    intro = f'''\n\n<!--00077案内開始-->
**最新は00077の[{MAIN}]({FOLDER}/{MAIN})。固定保有期限を外し、価格・板・二市場の方向変化で売買する188条件を検証。全30セッション、損失原因と改修、0/1/5秒待ちを掲載。**

[{ALL}]({FOLDER}/{ALL}) · [読む順序]({FOLDER}/README.md) · [公開会計]({FOLDER}/公開会計.json)。
<!--00077案内終了-->\n'''
    listing.write_text(head + intro + rest, encoding='utf8')
    root_readme = ROOT / 'README.md'
    body = root_readme.read_text(encoding='utf8')
    body = re.sub(r'最新の調査は .*?(?=\n\n)', f'最新の調査は **[00077：保有時間を決めない二市場方向追従](アルゴリズム調査/{FOLDER}/{MAIN})** です。[資料案内と読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。初回86＋原因別追加102条件を比較し、固定代表の全30場と注文待ち0・1・5秒を確認しました。', body, count=1)
    root_readme.write_text(body, encoding='utf8')
    save(PUBLIC / '公開指紋.json', dict(成果={p.name:digest(p) for p in sorted(PUBLIC.iterdir()) if p.is_file() and p.name != '公開指紋.json'}, 旧成果保持=preserved))
    print('00077の公開会計、読む順序、調査の入口を更新しました。')


if __name__ == '__main__':
    main()

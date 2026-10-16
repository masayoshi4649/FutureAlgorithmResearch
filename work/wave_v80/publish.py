"""新しい秒売買調査の案内と再現資料だけを公開し、過去成果を保持する。"""

from pathlib import Path
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FOLDER = '00076_5秒発注遅延を含む秒スキャルピング'
PUBLIC = ROOT / 'アルゴリズム調査' / FOLDER
MAIN = '秒スキャルピングの改善と全セッション損益.html'
ALL = '全330条件の前半比較.html'


def read(path: Path) -> object:
    """機能: UTF-8の保存済みJSONを読み込む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """機能: 公開する資料と保持する過去成果の内容を照合する。

    引数: path(Path)。返り値: SHA-256文字列(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, data: object) -> None:
    """機能: 今回の公開フォルダへJSONを保存する。

    引数: path(Path)、data(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(PUBLIC)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def main() -> None:
    """機能: 全会計・条件・読む順序を公開し、三つの入口案内を更新する。

    引数: なし。返り値: なし(None)。旧00074/00075の本文は変更しない。
    """
    assert (PUBLIC / MAIN).exists() and (PUBLIC / ALL).exists()
    preserved = {
        '00075_J2赤字上位セッションの板検証と防止策/赤字上位3セッションの板と防止策.html': '2ba151671bf9a181a6d017224788045ede7ed82a59bcfad439f10f83ad8b0026',
        '00075_J2赤字上位セッションの板検証と防止策/README.md': '77a3d7cf725e7286def7f4d2f0b6e99510491d053657d0bd41a59ef47c0c439a',
        '00074_歴代手法の再評価と二市場統合/過去の知見を統合した手法と全セッション損益.html': '79086d792f9e9aef423eb56fa5b54e04f8a656dd36a2024a16fc4773d6920b13',
        '00074_歴代手法の再評価と二市場統合/全162条件の比較.html': '5ef43354ca9399cc833aa3a54d601d0ffc90d421323b3f2831994cdb65bd5435',
    }
    assert all(digest(ROOT / 'アルゴリズム調査' / name) == value for name, value in preserved.items())
    data = read(HERE / 'report/描画資料.json')
    initial = read(HERE / '初回事前固定.json')
    repairs = read(HERE / '改修事前固定.json')
    chosen = read(HERE / '最終前半選定.json')
    quality = {p.stem: read(p) for p in sorted((HERE / 'quality_strict3/results').glob('*.json'))}
    audits = {p.stem: read(p) for p in sorted((HERE / 'audit').glob('*.json')) if '独立会計監査' in p.name or '実注文未来監査' in p.name or '前半選定' in p.name}
    save(PUBLIC / '公開会計.json', dict(期間=initial['全30'], 前半=initial['前16'], 後半=initial['後14'],
        集計='TOPIXミニ10枚・NK225マイクロ20枚。両商品を金額合算しない。利益/損失は各決済組の手数料後金額。無取引を勝ちに含めない。',
        遅延別=data['final'], 厳格3秒鮮度=quality, 監査=audits))
    save(PUBLIC / '検証条件と固定記録.json', dict(初回=initial, 改修=repairs, 最終選定=chosen,
        鮮度感度=read(HERE / 'quality_strict3/確認仕様.json'),
        再現元='../../work/wave_v80/', 旧成果保持=preserved,
        注意='注文時計は最終約定時刻の代理。実受信時計・実小型商品板・指値待ち順位の実証ではない。後14は過去研究で既知の期間。'))
    (PUBLIC / 'README.md').write_text(f'''# 00076：5秒発注遅延を含む秒スキャルピング

最初に **[{MAIN}]({MAIN})** を開いてください。

1. [{MAIN}]({MAIN})：結論、初回と改修の説明、全30セッションの利益・損失・収支、0・1・5秒の発注待ち比較。
2. [{ALL}]({ALL})：前16セッションで比較した初回288＋改修42条件。無取引・少数黒字も掲載。
3. [公開会計.json](公開会計.json)：11代表の全場会計、厳格3秒鮮度の感度、独立監査。
4. [検証条件と固定記録.json](検証条件と固定記録.json)：初回、原因別改修、代表固定と入力指紋。

損失の原因を調べて再検証しましたが、採用できる秒売買手法は確認できませんでした。全30場・5秒待ちの改修成行A6は、TOPIXミニ10枚で−942,860円、日経マイクロ20枚で−285,040円。総損失額は減っても取引回数が減った影響が大きく、1決済組あたりの平均収支は両商品とも初回成行より悪化しました。

各注文に立会手数料を課金し、買いは売気配、売りは買気配を使います。待機指値は1呼値貫通後に元指値で約定する仮定です。判断後5秒に必ず約定するモデルではなく、5秒経過後の最初の有効観測で約定するため、観測待ちが加わります。元データには真の受信時計とミニ・マイクロ自身の板がなく、秒単位の実運用成績は未確認です。

前16で条件と代表を選び、固定後に後14を再生しました。後14も過去研究で既知の期間なので、未知データによる検証とは呼びません。最新API取得・実注文は行っていません。

## 再現資料

- [入口仕様](../../work/wave_v80/design/入口仕様.json)、[初回の損失診断](../../work/wave_v80/diagnosis/初回主3の損失原因.json)、[監査の読む順序](../../work/wave_v80/audit/README.md)。
- [売買エンジン](../../work/wave_v80/engine.py)、[前半探索](../../work/wave_v80/study.py)、[原因に対応する改修](../../work/wave_v80/pdca.py)、[情報鮮度の比較](../../work/wave_v80/freshness.py)。
- [HTML生成](../../work/wave_v80/report/generate.py)。Python環境と保存済み素材を用い、プロジェクトルートから実行します。

```text
python -X utf8 work/wave_v80/pdca.py --final --delay 5 --workers 6
python -X utf8 work/wave_v80/freshness.py
python -X utf8 work/wave_v80/audit/accounts.py --stage final/delay5 --count 11
python -X utf8 work/wave_v80/report/generate.py
python -X utf8 work/wave_v80/publish.py
```

再生は既存の結果を再利用し、独立会計監査は保存台帳から再集計します。入力・実装の固定指紋が異なる場合は再生を停止します。条件を変える場合は既存結果へ上書きせず、新しい作業で比較してください。
''', encoding='utf-8')

    # ----------------------------------------
    research = ROOT / 'アルゴリズム調査'
    index = research / 'index.html'
    body = index.read_text(encoding='utf-8')
    block = f'''<!--00076開始--><article class="task latest"><div class="number">作業00076 <span class="badge">最新</span></div><h2>5秒発注遅延を含む秒スキャルピング</h2><p>初回288条件を損失分解し、42条件へ改修して再確認。固定11代表の全30場、0・1・5秒の注文待ち、情報鮮度の感度を掲載。総赤字の減少と1取引の改善を区別。</p><a class="button" href="{FOLDER}/{MAIN}">説明と全セッション損益を開く →</a><p><a href="{FOLDER}/{ALL}">全330条件の前半比較</a> · <a href="{FOLDER}/README.md">資料案内</a> · <a href="{FOLDER}/公開会計.json">公開会計</a></p></article><!--00076終了-->'''
    body = re.sub(r'<!--00076開始-->.*?<!--00076終了-->\s*', '', body, flags=re.S)
    body = body.replace('class="task latest"', 'class="task"').replace('<span class="badge">最新</span>', '')
    body = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新00076：秒スキャルピング330条件と損失原因別の改修。両商品で安定して利益が残る方法は未確認。固定代表の全30セッションを掲載。</p>', body, count=1, flags=re.S)
    body = body.replace('<!--00075開始-->', block + '\n<!--00075開始-->', 1)
    body = re.sub(r'<footer>.*?</footer>', '<footer>最新作業は00076です。次の作業は00077以降へ追加します。</footer>', body, count=1, flags=re.S)
    index.write_text(body, encoding='utf-8')
    listing = research / 'README.md'
    body = listing.read_text(encoding='utf-8')
    body = re.sub(r'<!--00076案内開始-->.*?<!--00076案内終了-->\s*', '', body, flags=re.S)
    body = body.replace('**最新は00075の', '**00075の')
    head, rest = body.split('\n', 1)
    intro = f'''\n\n<!--00076案内開始-->
**最新は00076の[{MAIN}]({FOLDER}/{MAIN})。初回288＋原因別改修42条件を比較し、固定11代表の全30場を掲載。総損失額の減少だけでは安定化と判定せず、利益喪失・平均収支・発注待ちも比較。**

[{ALL}]({FOLDER}/{ALL}) · [読む順序]({FOLDER}/README.md) · [公開会計]({FOLDER}/公開会計.json)。
<!--00076案内終了-->\n'''
    listing.write_text(head + intro + rest, encoding='utf-8')
    root_readme = ROOT / 'README.md'
    body = root_readme.read_text(encoding='utf-8')
    body = re.sub(r'最新の調査は .*?(?=\n\n)', f'最新の調査は **[00076：5秒発注遅延を含む秒スキャルピング](アルゴリズム調査/{FOLDER}/{MAIN})** です。[資料案内と読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。初回288条件を診断して42条件を改修し、固定代表の全30場と注文遅延0・1・5秒を再確認しました。', body, count=1)
    root_readme.write_text(body, encoding='utf-8')
    save(PUBLIC / '公開指紋.json', dict(成果={p.name: digest(p) for p in sorted(PUBLIC.iterdir()) if p.is_file() and p.name != '公開指紋.json'}, 旧成果保持=preserved))
    print('00076の会計・条件・案内と三つの入口を更新しました。')


if __name__ == '__main__':
    main()

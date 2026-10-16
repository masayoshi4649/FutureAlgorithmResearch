"""E01原版と固定改修の全セッション会計を新作業へ公開する。"""
from pathlib import Path
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / 'アルゴリズム調査'
FOLDER = '00081_E01原版と知見統合改修の再検証'
PUBLIC = RESEARCH / FOLDER
MAIN = 'E01原版と改修の説明と全セッション損益.html'
DETAIL = '検証詳細.html'
ALL = '全25条件の比較.html'


def read(path):
    """
    機能: 日本語の検証記録を読む。
    引数: path(Path)。
    返り値: object。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    """
    機能: 成果と原資料の内容指紋を計算する。
    引数: path(Path)。
    返り値: strのSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    """
    機能: 新作業の公開資料だけを保存する。
    引数: path(Path)、value(object)。
    返り値: None。
    """
    assert path.resolve().is_relative_to(PUBLIC.resolve())
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def main():
    """
    機能: 会計・固定条件・監査と読む順序を公開し、一覧を更新する。
    引数: なし。
    返り値: None。旧成果は指紋確認し変更しない。
    """
    assert all((PUBLIC / name).exists() for name in (MAIN, DETAIL, ALL))
    old = RESEARCH / '00080_順行逆指値と反転売買の検証'
    old_hashes = read(old / '公開指紋.json')['成果']
    preserved = {str((old / name).relative_to(RESEARCH)): expected for name, expected in old_hashes.items()}
    assert all(digest(RESEARCH / name) == expected for name, expected in preserved.items())
    fixed = read(HERE / 'results/事前固定.json')
    results = {model: {c['id']: read(HERE / model / 'results' / (c['id'] + '.json')) for c in fixed['catalog']}
               for model in fixed['models']}
    audits = {p.name: read(p) for p in sorted((HERE / 'audit').glob('*.json'))}
    checks = {p.name: read(p) for p in sorted((HERE / 'report').glob('*.json'))
              if p.name == '生成結果.json' or any(x in p.name for x in ('検査', '監査', '検証'))}
    # ----------------------------------------
    # 旧画面への表示検査は当時の記録として残し、現行の簡潔版検査と区別する。
    previous_display = {}
    for name in ('公開HTMLの数値と解釈監査.json', '独立監査総括.json'):
        if name in audits:
            previous_display[name] = audits.pop(name)
    if 'HTML表示の独立検査.json' in checks:
        previous_display['HTML表示の独立検査.json'] = checks.pop('HTML表示の独立検査.json')
    analysis = {p.name: read(p) for p in sorted((HERE / 'analysis').glob('*.json'))}
    save(PUBLIC / '公開会計.json', dict(全30=fixed['全30'], 観測現在値=results['observed'],
         旧指定条件価格=results['specified'], 独立監査=audits, 表示検査=checks,
         前版の表示検査と総括=previous_display,
         会計='初回から全返済までの組と部分決済脚を区別。全残玉を清算し、両側注文の手数料を含める。'))
    save(PUBLIC / '検証条件と固定記録.json', dict(事前固定=fixed,
         入力準備=read(HERE / 'prepared/入力準備の完了.json'),
         原版考証=read(HERE / 'theory/E01原版と過去改修の仕様考証.json'),
         改修の作用=analysis, 旧成果保持=preserved))
    # ----------------------------------------
    conclusion = read(HERE / 'report/結論文.json')
    selected = results['observed']['E01_G_U']['periods']['全30']
    table = ['| 商品 | 全30場の純収支 | 最大下落 | 黒字セッション |', '| --- | ---: | ---: | ---: |']
    for symbol, label in [('TOPIX', 'TOPIXミニ・初回5枚'), ('NK225', '日経マイクロ・初回10枚')]:
        m = selected[symbol]
        table.append(f'| {label} | {m["net"]:,.0f}円 | {m["max_drawdown"]:,.0f}円 | {m["positive_sessions"]}/30 |')
    (PUBLIC / 'README.md').write_text(f'''# 00081：安定性を重視して一つ選ぶならE01_G_U

最初に **[{MAIN}]({MAIN})** を開いてください。結論・手法・両商品の成績だけを短くまとめています。

**{conclusion['要旨']}**

E01_G_Uは、両市場の方向を入口で再確認し、米国現物開始前後15分は保有玉を返済して静観する方式です。元E01の追跡新規・途中半減・段階トレーリングを維持します。

{chr(10).join(table)}

評価は「純収支÷最大下落」。今回の25条件で両商品とも最高（JUと同値）ですが、毎日黒字・将来の安定性を保証する意味ではありません。観測現在値で全再生した、手数料後の仮想成績です。ラージ価格を小型商品の倍率で換算しており、実際の小型商品の売買気配や部分約定は再現していません。

詳しく調べる場合：

- [検証詳細]({DETAIL})：原版・改修・時間見送りと、全30場の損益・枚数。
- [全25条件]({ALL})：保存結果を同じ期間・会計で比較。
- [公開会計](公開会計.json)、[固定条件と検証記録](検証条件と固定記録.json)：全結果・監査・再現根拠。

対象は2026/09/21デイ〜10/09ナイトの既知30場。初回5枚／10枚、上限10枚／20枚、追加なし・場内全返済。米国開始は[NYSE公式](https://www.nyse.com/markets/hours-calendars)の東部時間09:30を基準とし、今回の夏時間では日本22:15〜22:45を見送ります。旧影時計を維持するため、再参加はさらに遅くなる場合があります。

主3条件（原E01・G・全統合）の事前固定は変更していません。この一本への絞込みは、既知の保存結果を安定性の観点で読むための選択です。戦略・相場データ・App/E01は今回の表示整理で変更していません。

再生成：`python -X utf8 work/wave_v85/report/build.py`、続いて `python -X utf8 work/wave_v85/publish.py`。
''', encoding='utf-8')
    # ----------------------------------------
    index = RESEARCH / 'index.html'
    body = index.read_text(encoding='utf-8')
    body = re.sub(r'<!--00081開始-->.*?<!--00081終了-->\s*', '', body, flags=re.S)
    body = body.replace('class="task latest"', 'class="task"').replace('<span class="badge">最新</span>', '')
    block = f'''<!--00081開始--><article class="task latest"><div class="number">作業00081 <span class="badge">最新</span></div><h2>E01原版と知見統合改修の再検証</h2><p>安定性を重視して一つ選ぶならE01_G_U。短い結論と両商品の成績、必要な場合だけ全30場を確認できます。</p><a class="primary" href="{FOLDER}/{MAIN}">一本に絞った結論を開く</a><a href="{FOLDER}/{DETAIL}">検証詳細</a><a href="{FOLDER}/{ALL}">全25条件</a><a href="{FOLDER}/README.md">読む順序</a></article><!--00081終了-->\n'''
    marker = re.search(r'<article\s+class="task', body)
    assert marker is not None
    position = marker.start()
    opening = re.search(r'<!--\d{5}開始-->\s*$', body[:position])
    if opening:
        position = opening.start()
    body = body[:position] + block + body[position:]
    index.write_text(body, encoding='utf-8')
    listing = RESEARCH / 'README.md'
    body = listing.read_text(encoding='utf-8')
    body = re.sub(r'<!--00081案内開始-->.*?<!--00081案内終了-->\s*', '', body, flags=re.S)
    body = body.replace('**最新は00080', '**00080')
    first, rest = body.split('\n', 1)
    listing.write_text(first + f'''\n\n<!--00081案内開始-->
**最新は00081の[{MAIN}]({FOLDER}/{MAIN})。一つ選ぶならE01_G_U。短い結論・成績と、折り畳みの全30場損益。**

[検証詳細]({FOLDER}/{DETAIL}) · [{ALL}]({FOLDER}/{ALL}) · [読む順序]({FOLDER}/README.md)。
<!--00081案内終了-->
''' + rest, encoding='utf-8')
    root_readme = ROOT / 'README.md'
    body = root_readme.read_text(encoding='utf-8')
    body = re.sub(r'最新の調査は .*?(?=\n\n)', f'最新の調査は **[00081：E01原版と知見統合改修の再検証](アルゴリズム調査/{FOLDER}/{MAIN})** です。[読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。一つ選ぶならE01_G_Uという結論を先頭に、成績を短く整理しました。', body, count=1)
    root_readme.write_text(body, encoding='utf-8')
    save(PUBLIC / '公開指紋.json', dict(HTML={name: digest(PUBLIC / name) for name in (MAIN, DETAIL, ALL)}, 成果={p.name: digest(p) for p in PUBLIC.iterdir()
         if p.is_file() and p.name != '公開指紋.json'}, 旧成果保持=preserved))
    print('00081の短い結論・詳細・全比較と、読む順序を更新しました。')


if __name__ == '__main__':
    main()

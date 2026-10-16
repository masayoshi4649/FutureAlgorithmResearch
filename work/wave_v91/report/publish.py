"""全会計・表示の監査後に00087を公開し、過去フォルダを保持する。"""

import hashlib
import json
from pathlib import Path
import re
import shutil

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
RESEARCH = ROOT / 'アルゴリズム調査'
FOLDER = '00087_待機基準の保持と二市場反対による返済'
OUT = RESEARCH / FOLDER
MAIN = OUT / '待機基準と反対返済の改善と全セッション損益.html'


def read(path: Path) -> dict:
    """
    機能: 日本語の検証資料を読む。
    引数: path(Path)。
    返り値: dict。保存されたJSONの内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """
    機能: 公開資料と旧成果の内容指紋を計算する。
    引数: path(Path)。
    返り値: str。SHA256の16進表記。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def main() -> None:
    """
    機能: 最終監査の成功を確認し、資料案内と最新入口だけを更新する。
    引数: なし。
    返り値: None。生データ・旧作業フォルダ・売買条件を変更しない。
    """
    fixed_path = WORK / '事前固定.json'
    fixed = read(fixed_path)
    for relative, expected in fixed['SHA256'].items():
        assert sha(ROOT / relative) == expected, relative
    account_path = WORK / 'analysis/比較結果.json'
    account = read(account_path)
    audit_path = WORK / 'audit/全38条件全31場の仮説と最初返済及び全原板清算会計の独立検算.json'
    audit = read(audit_path)
    assert audit['全合格'] and audit['検査件数']['全口座'] == 2356
    for relative, expected in audit['SHA256'].items():
        assert sha(ROOT / relative) == expected, relative
    reviewed = read(WORK / 'review/根担当全31集計と独立解釈の数値照合.json')
    assert reviewed['全合格']
    mixing = read(WORK / 'review/固定配分の親別金額利益割合の上限と適用限界.json')
    assert mixing['全合格']
    display = read(HERE / '表示の独立検査.json')
    generated = read(HERE / '生成結果.json')
    assert display['全合格'] and display['目視確認']
    assert display['HTML_SHA256'] == generated['HTML_SHA256'] == sha(MAIN)
    assert len(display['画面']) == 5 and all(view['全合格'] for view in display['画面'])
    assert not account['both80'] and not account['両商品で全場黒字']
    # ----------------------------------------
    # 旧作業の全ファイルを前後で照合し、公開入口の更新と区別する。
    old = RESEARCH / '00086_二市場の状態で追従と指値反発を配分'
    prior = {str(path.relative_to(ROOT)): sha(path) for path in old.rglob('*') if path.is_file()}
    assert prior[str((old / '二つの戦略への配分と全セッション損益.html').relative_to(ROOT))] == \
        '912d74cb54d58cabbb94889a2f39a2c83d3f66afd9b7388e2f9bb8c89f787637'
    shutil.copyfile(account_path, OUT / '公開会計.json')
    assert sha(OUT / '公開会計.json') == sha(account_path)
    guide = '''# 00087 待機基準の保持と二市場反対による返済

最初に **[待機基準と反対返済の改善と全セッション損益.html](待機基準と反対返済の改善と全セッション損益.html)** を開いてください。全38条件を切り替え、TOPIXミニ10枚・日経マイクロ20枚を上限とした全31場の利益・損失・収支と決済枚数を確認できます。

読む順序は短い結論→追加10月12日デイ→比較→全場表です。条件と原因は必要な時だけ詳細を開いてください。[公開会計](公開会計.json)が表の原数値です。

追従8：反発2の併用は追従単独に対し、TOPIXで77,216円改善、日経で51,280円悪化し、両商品で最大下落が増えました。今回の比較では追従単独J8/J10が悪い側の金額利益割合で最上位ですが、55.8%・56.5%で目標80%には届きません。異なる性質の戦略を併用する価値と、この反発戦略を採用できるかは別に評価します。

同じ枚数上限で追従10を追従8：反発2へ配分した場合、TOPIXでは最大下落を39,382円減らす効果がありましたが、収支は32,840円減少。日経は収支97,832円減少・最大下落9,384円増加でした。未使用枠へ反発を足す比較と、追従の枠を反発へ置き換える比較を分けています。

固定配分で売買経路を変えなければ、親別の金額利益割合は各戦略の割合の加重平均です。今回の低い損益相関だけでは、最高の戦略を超える利益割合になりません。日々の収支を平準化する価値は残りますが、80%の目標には参加条件や売買そのものの改善が必要です。

事前固定の統合主はTOPIX+457,134円・日経−215,624円で不採用。追加日を見る前に旧前16場で固定した参考O10_F15は+322,928円・+437,160円ですが、金額利益割合51.2%・52.6%にとどまります。平均勝ち額が負け額の2倍以上でも、負けの頻度が多ければ安定収益になりません。追加日の主TOPIXは無取引で、勝ちに数えません。

旧30場は既知データでの再探索。追加1場は条件と参考代表を固定した後の初回確認です。ラージ板の次有効買ask・売bidで全量約定する代理モデルを使用し、全保有玉の含み損と返済料も評価。追加5秒遅延はありません。小商品実板、待ち順位、真の通信受信時計は未検証です。全場をセッション内で全返済しました。

再現と独立監査は以下を参照してください。

- [38条件の事前固定](../../work/wave_v91/事前固定.json)と[前16場による参考固定](../../work/wave_v91/前16参考代表.json)。
- [実行スクリプト](../../work/wave_v91/research.py)と[旧30＋追加1の集計](../../work/wave_v91/analysis/assemble.py)。
- [全2,356口座の独立監査](../../work/wave_v91/audit/全38条件全31場の仮説と最初返済及び全原板清算会計の独立検算.json)。
- [同一新規と後続経路の原因分析](../../work/wave_v91/review/旧38の独立会計と同一新規及び経路変化の部品分解.json)と[赤字上位3場の具体時刻](../../work/wave_v91/review/主と旧前16参考代表の赤字上位3場と具体的な価格反証.json)。
- [全31場の敵対的結論](../../work/wave_v91/review/全31の独立会計と部品改修の敵対的結論.json)。
- [配分の数学的な上限と適用範囲](../../work/wave_v91/review/固定配分の親別金額利益割合の上限と適用限界.json)と[日々の損益の相関](../../work/wave_v91/review/固定配分の相関と場収支のぶれの診断.json)。

現在API取得0回・実注文0回。旧00086を保持し、利益80%へ向けた調査は継続中です。
'''
    (OUT / 'README.md').write_text(guide, encoding='utf-8')
    # ----------------------------------------
    # 最新作業を三つの入口へ登録し、既存の作業リンクは残す。
    root_readme = ROOT / 'README.md'
    source = root_readme.read_text(encoding='utf-8')
    new_line = (f'最新の調査は **[00087：待機基準の保持と二市場反対による返済]'
                f'(アルゴリズム調査/{FOLDER}/{MAIN.name})** です。38条件・全31場を比較し、'
                f'追加10月12日デイを固定後に確認。[読む順序](アルゴリズム調査/{FOLDER}/README.md)'
                'も参照してください。利益80%への調査は継続中です。')
    source, count = re.subn(r'^最新の調査は .*$', lambda match: new_line, source, count=1, flags=re.M)
    assert count == 1
    root_readme.write_text(source, encoding='utf-8')
    research_readme = RESEARCH / 'README.md'
    source = research_readme.read_text(encoding='utf-8')
    if '<!--00087案内開始-->' not in source:
        block = (f'<!--00087案内開始-->\n**最新は00087の[{MAIN.name}]({FOLDER}/{MAIN.name})。'
                 '待機保持・反対返済・幅・利益保護・保有期限を切り分けた38条件、全31場。**\n\n'
                 f'[読む順序]({FOLDER}/README.md) · [公開会計]({FOLDER}/公開会計.json)。'
                 '利益80%への調査は継続中です。\n<!--00087案内終了-->\n\n')
        assert '<!--00086案内開始-->' in source
        source = source.replace('**最新は00086の', '**00086の', 1)
        source = source.replace('<!--00086案内開始-->', block + '<!--00086案内開始-->', 1)
    research_readme.write_text(source, encoding='utf-8')
    index = RESEARCH / 'index.html'
    source = index.read_text(encoding='utf-8')
    if '<!--00087開始-->' not in source:
        source = source.replace('class="task latest"', 'class="task"')
        source = source.replace(' <span class="badge">最新</span>', '')
        article = (f'<!--00087開始--><article class="task latest"><div class="number">作業00087 '
                   '<span class="badge">最新</span></div><h2>待機基準の保持と二市場反対による返済</h2>'
                   '<p>部品別と統合の38条件を全31場で比較。追加デイは条件固定後に確認。'
                   '複数手法の配分による安定化と金額利益80%は未達です。</p>'
                   f'<a class="button" href="{FOLDER}/{MAIN.name}">説明と全場損益</a> '
                   f'<a href="{FOLDER}/README.md">読む順序</a></article><!--00087終了-->\n')
        assert '<!--00086開始-->' in source
        source = source.replace('<!--00086開始-->', article + '<!--00086開始-->', 1)
    source = re.sub(r'<p class="lead">最新0008[67]：.*?</p>',
                    '<p class="lead">最新00087：待機保持と反対返済の38条件。全31場の損益と、固定後の追加デイを掲載します。</p>',
                    source, count=1)
    index.write_text(source, encoding='utf-8')
    assert prior == {str(path.relative_to(ROOT)): sha(path) for path in old.rglob('*') if path.is_file()}
    outputs = [MAIN, OUT / 'README.md', OUT / '公開会計.json', root_readme, research_readme, index]
    proof = dict(全合格=True, HTML_SHA256=sha(MAIN), 全口座=2356,
                 旧00086全成果不変=True, 旧00086指紋=prior,
                 公開指紋={str(path.relative_to(ROOT)): sha(path) for path in outputs},
                 条件及び代表の差替え=False, API取得=0, 実注文=0)
    (HERE / '公開結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in proof.items() if k != '旧00086指紋'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

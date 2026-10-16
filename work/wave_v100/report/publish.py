"""会計と画面の検査が終わった00096だけを公開し、過去の調査を保持する。"""

import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
NAME = '00096_元候補からの入口価格上限と安定性'
TITLE = '追いかける価格を制限した手法と全セッション損益.html'


def read(path: Path) -> dict:
    """
    機能: 正式会計又は合格証跡を読み込む。
    引数: path(Path)はJSONファイル。
    返り値: dict。保存済み資料。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 公開直前と公開後の同一性を検査する。
    引数: path(Path)はファイル。
    返り値: str。SHA256の16進文字列。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 正式会計・表示一致・根の目視後に新調査と案内を公開する。
    引数: なし。
    返り値: None。旧89から95の全成果を変更しない。新番号の既存成果も上書きしない。
    """
    generated = read(HERE / '生成結果.json')
    display = read(HERE / '表示の独立検査.json')
    visual = read(HERE / '根担当の目視確認.json')
    account = read(WORK / 'analysis/比較結果.json')
    explanation = read(WORK / 'analysis/説明補足.json')
    assert generated['全合格'] and display['全合格'] and visual['全合格']
    assert generated['条件数'] == display['保存結果一致数'] == 34
    assert generated['口座数'] == display['保存会計口座数'] == 2108
    assert explanation['全合格'] and explanation['正式全範囲独立検算完了']
    assert explanation['独立原因検査完了'] and explanation['売買及び会計の変更'] == 0
    assert explanation['根集計SHA256'] == digest(WORK / 'analysis/比較結果.json')
    assert generated['理論主'] == account['primary'] == 'P1_L1_C1_A1_X1'
    assert visual['表示検査SHA256'] == digest(HERE / '表示の独立検査.json')
    assert visual['生成結果SHA256'] == digest(HERE / '生成結果.json')
    assert len(display['画面']) == len(visual['画像SHA256']) == 5
    assert set(visual['画像SHA256']) == {
        str(Path(row['画像']).relative_to(ROOT)) for row in display['画面']}
    source = HERE / '公開前' / TITLE
    assert digest(source) == generated['HTML_SHA256'] == display['HTML_SHA256'] == visual['HTML_SHA256']
    for relative, expected in generated['使用資料SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    for relative, expected in display['表示検査コードSHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    for relative, expected in visual['画像SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    target = ROOT / 'アルゴリズム調査' / NAME
    assert not target.exists(), '新しい作業番号の既存成果を上書きしません'
    numbers = [int(p.name[:5]) for p in target.parent.iterdir()
               if p.is_dir() and re.match(r'^\d{5}_', p.name)]
    assert max(numbers) == 95
    prior = {}
    for serial in (89, 90, 91, 92, 93, 94, 95):
        folder = next(target.parent.glob(f'{serial:05d}_*'))
        prior.update({str(p.relative_to(ROOT)): digest(p) for p in folder.rglob("*") if p.is_file()})
    target.mkdir()
    (target / TITLE).write_bytes(source.read_bytes())
    (target / '公開会計.json').write_bytes((WORK / 'analysis/比較結果.json').read_bytes())
    readme = f'''# 元候補からの入口価格上限と安定性

最初に[説明と全セッション損益]({TITLE})を開いてください。

読む順序は、短い結論、安定性の比較、手法選択と全31セッション損益です。詳しい条件と原因は折りたたみ内に掲載します。

旧候補を固定し、4判断価格上限×2現在支持源×2待機入口×2出口と即時2対照の34条件で比較しました。全条件TOPIXmini8枚・NK225micro16枚です。手数料を含み、全玉をセッション内で返済します。全31場は既知の再探索です。

保存済みの会計は[公開会計.json](公開会計.json)。再現コードと独立検査は[work/wave_v100](../../work/wave_v100)にあります。現在API取得と実注文は行っていません。
'''
    (target / 'README.md').write_text(readme, encoding='utf-8')
    # ----------------------------------------
    # 入口の案内だけ更新し、旧調査のリンクと成果を保持する。
    main_readme = ROOT / 'README.md'
    text = main_readme.read_text(encoding='utf-8')
    latest = f'最新の調査は **[00096：元候補からの入口価格上限と安定性](アルゴリズム調査/{NAME}/{TITLE})** です。34条件・全31既知場の赤字率と平均・最大赤字、活動と全場損益を比較。[読む順序](アルゴリズム調査/{NAME}/README.md)も参照してください。両銘柄の安定収益と金額利益80%への調査は継続中です。'
    text, count = re.subn(r'最新の調査は[^\n]+', latest, text, count=1)
    assert count == 1
    main_readme.write_text(text, encoding='utf-8')
    index_readme = target.parent / 'README.md'
    text = index_readme.read_text(encoding='utf-8').replace('**最新は00095の', '**00095の', 1)
    announcement = f'<!--00096案内開始-->\n**最新は00096の[説明と全セッション損益]({NAME}/{TITLE})。4判断価格上限・2現在支持源・2待機入口・2出口の34条件、全31場の赤字額と活動黒字数を比較。**\n\n[読む順序]({NAME}/README.md) · [公開会計]({NAME}/公開会計.json)。全31は既知期間です。\n<!--00096案内終了-->\n\n'
    anchor = '<!--00095案内開始-->'
    assert anchor in text
    index_readme.write_text(text.replace(anchor, announcement+anchor, 1), encoding='utf-8')
    index_html = target.parent / 'index.html'
    text = index_html.read_text(encoding='utf-8').replace('作業00095 · 最新', '作業00095', 1)
    article = f'<!--00096開始--><article class="task"><div class="number">作業00096 · 最新</div><h2>元候補からの入口価格上限と安定性</h2><p>4判断価格上限・2現在支持源・2待機入口・2出口と即時対照の34条件。最大利益より各セッションの赤字抑制を優先し、両商品の全31場損益を掲載。</p><a class="primary" href="{NAME}/{TITLE}">説明と全セッション損益を開く</a> <a href="{NAME}/README.md">読む順序</a></article><!--00096終了-->\n'
    anchor = '<!--00095開始-->'
    assert anchor in text
    index_html.write_text(text.replace(anchor, article+anchor, 1), encoding='utf-8')
    for relative, expected in prior.items():
        assert digest(ROOT / relative) == expected, relative
    assert digest(target / TITLE) == generated['HTML_SHA256']
    assert read(target / '公開会計.json') == account
    outputs = [target / TITLE, target / '公開会計.json', target / 'README.md',
               main_readme, index_readme, index_html]
    proof = dict(全合格=True, 全34全31会計と画面一致=True, 旧成果不変=True, 旧89から95全成果不変=True,
                 公開資料=str((target / TITLE).relative_to(ROOT)),
                 公開SHA256={str(p.relative_to(ROOT)): digest(p) for p in outputs},
                 旧成果SHA256=prior, API取得=0, 実注文=0, 全31既知=True, 未見確認場数=0)
    (HERE / '公開結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

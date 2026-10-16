"""会計と画面の検査が終わった00092だけを公開し、過去の調査を保持する。"""

import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
NAME = '00092_初期損切りと順行後の利益保護'
TITLE = '初期損切りと利益保護の説明と全セッション損益.html'


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
    返り値: None。過去の調査HTMLと会計を変更しない。
    """
    generated = read(HERE / '生成結果.json')
    display = read(HERE / '表示の独立検査.json')
    visual = read(HERE / '根担当の目視確認.json')
    account = read(WORK / 'analysis/比較結果.json')
    assert generated['全合格'] and display['全合格'] and visual['全合格']
    assert generated['条件数'] == display['保存結果一致数'] == 18
    assert generated['口座数'] == display['保存会計口座数'] == 1116
    source = HERE / '公開前' / TITLE
    assert digest(source) == generated['HTML_SHA256'] == display['HTML_SHA256'] == visual['HTML_SHA256']
    for relative, expected in generated['使用資料SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    for relative, expected in visual['画像SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    target = ROOT / 'アルゴリズム調査' / NAME
    assert not target.exists(), '新しい作業番号の既存成果を上書きしません'
    numbers = [int(p.name[:5]) for p in target.parent.iterdir()
               if p.is_dir() and re.match(r'^\d{5}_', p.name)]
    assert max(numbers) == 91
    prior = {}
    for serial in (88, 89, 90, 91):
        folder = next(target.parent.glob(f'{serial:05d}_*'))
        prior.update({str(p.relative_to(ROOT)): digest(p) for p in folder.iterdir() if p.is_file()})
    target.mkdir()
    (target / TITLE).write_bytes(source.read_bytes())
    (target / '公開会計.json').write_bytes((WORK / 'analysis/比較結果.json').read_bytes())
    readme = f'''# 初期損切りと順行後の利益保護

最初に[説明と全セッション損益]({TITLE})を開いてください。

読む順序は、短い結論、安定性の比較、手法選択と全31セッション損益です。詳しい条件と原因は折りたたみ内に掲載します。

旧J8の入口とTOPIXmini8枚・NK225micro16枚を固定し、初期幅、利益床、通常期限を18条件で比較しました。経済的な独立条件は14組です。手数料を含み、全玉をセッション内で返済します。全31場は既知の再探索です。

保存済みの会計は[公開会計.json](公開会計.json)。再現コードと独立検査は[work/wave_v96](../../work/wave_v96)にあります。現在API取得と実注文は行っていません。
'''
    (target / 'README.md').write_text(readme, encoding='utf-8')
    # ----------------------------------------
    # 入口の案内だけ更新し、旧調査のリンクと成果を保持する。
    main_readme = ROOT / 'README.md'
    text = main_readme.read_text(encoding='utf-8')
    latest = f'最新の調査は **[00092：初期損切りと順行後の利益保護](アルゴリズム調査/{NAME}/{TITLE})** です。18条件・全31既知場の赤字抑制と全場損益を比較。[読む順序](アルゴリズム調査/{NAME}/README.md)も参照してください。両銘柄の安定収益と金額利益80%への調査は継続中です。'
    text, count = re.subn(r'最新の調査は[^\n]+', latest, text, count=1)
    assert count == 1
    main_readme.write_text(text, encoding='utf-8')
    index_readme = target.parent / 'README.md'
    text = index_readme.read_text(encoding='utf-8').replace('**最新は00091の', '**00091の', 1)
    announcement = f'<!--00092案内開始-->\n**最新は00092の[説明と全セッション損益]({NAME}/{TITLE})。初期停止と順行後保護の18条件、全31場の赤字額と活動黒字数を比較。**\n\n[読む順序]({NAME}/README.md) · [公開会計]({NAME}/公開会計.json)。全31は既知期間です。\n<!--00092案内終了-->\n\n'
    anchor = '<!--00091案内開始-->'
    assert anchor in text
    index_readme.write_text(text.replace(anchor, announcement+anchor, 1), encoding='utf-8')
    index_html = target.parent / 'index.html'
    text = index_html.read_text(encoding='utf-8').replace('作業00091 · 最新', '作業00091', 1)
    article = f'<!--00092開始--><article class="task"><div class="number">作業00092 · 最新</div><h2>初期損切りと順行後の利益保護</h2><p>入口を固定した18条件。最大利益より各セッションの赤字抑制を優先し、両商品の全31場損益を掲載。</p><a class="primary" href="{NAME}/{TITLE}">説明と全セッション損益を開く</a> <a href="{NAME}/README.md">読む順序</a></article><!--00092終了-->\n'
    anchor = '<!--00091開始-->'
    assert anchor in text
    index_html.write_text(text.replace(anchor, article+anchor, 1), encoding='utf-8')
    for relative, expected in prior.items():
        assert digest(ROOT / relative) == expected, relative
    assert digest(target / TITLE) == generated['HTML_SHA256']
    assert read(target / '公開会計.json') == account
    outputs = [target / TITLE, target / '公開会計.json', target / 'README.md',
               main_readme, index_readme, index_html]
    proof = dict(全合格=True, 全18全31会計と画面一致=True, 旧成果不変=True,
                 公開資料=str((target / TITLE).relative_to(ROOT)),
                 公開SHA256={str(p.relative_to(ROOT)): digest(p) for p in outputs},
                 API取得=0, 実注文=0, 全31既知=True, 未見確認場数=0)
    (HERE / '公開結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

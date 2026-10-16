"""全数会計・独立原因・表示と根の目視後に00098を公開し、旧成果を保持する。"""

import argparse
import hashlib
import json
from pathlib import Path
import re

from verify import ADDITIONAL, ADDITIONAL_AUDIT, CAUSE, fingerprint_for, formal_evidence

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
NAME = '00098_増玉の停止余裕と線保全の再検証'
TITLE = '増玉の停止余裕を残す手法と全セッション損益.html'


def read(path: Path) -> dict:
    """
    機能: 公開に必要な合格証跡を読み込む。
    引数: path(Path)。
    返り値: dict。保存したJSON。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 公開する内容と既存成果の不変性を照合する。
    引数: path(Path)。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 検証済みHTMLと全20会計を新番号へ公開して案内を更新する。
    引数: CLIの--root-four-images-reviewed (bool) は根の全4画像閲覧と公開許可。
    返り値: None。売買条件、会計、旧作業を変更しない。
    """
    parser = argparse.ArgumentParser(description='元31と追加40の独立会計・全32合算・原因・表示・根目視後だけ00098を公開します。')
    parser.add_argument('--root-four-images-reviewed', action='store_true')
    args = parser.parse_args()
    assert args.root_four_images_reviewed, '根による全4画像の実閲覧と公開許可が必要です'
    assert not (HERE / '公開結果.json').exists(), '公開記録を上書きしません'
    evidence = formal_evidence()
    generated = read(HERE / '生成結果.json')
    display = read(HERE / '表示の独立検査.json')
    visual = read(HERE / '根担当の目視確認.json')
    audit, cause, cause_path = evidence['audit'], evidence['cause'], CAUSE
    assert generated['全合格'] and display['全合格'] and visual['全合格']
    assert audit['合格'] and not audit['人工専用']
    assert cause['全合格'] is True
    assert generated['条件数'] == display['保存結果一致数'] == 20
    assert generated['口座数'] == display['保存会計口座数'] == audit['検査件数']['口座'] == 1240
    assert display['保存追加会計口座数'] == evidence['additional_audit']['検査件数']['口座'] == 40
    assert display['保存全32口座数'] == evidence['additional']['全32口座数'] == 1280
    for path in (ADDITIONAL, ADDITIONAL_AUDIT):
        assert fingerprint_for(generated['使用資料SHA256'], path) == digest(path)
    assert generated['HTML_SHA256'] == display['HTML_SHA256'] == visual['HTML_SHA256']
    assert visual['表示検査SHA256'] == digest(HERE / '表示の独立検査.json')
    assert visual['生成結果SHA256'] == digest(HERE / '生成結果.json')
    assert len(display['画面']) == len(visual['画像SHA256']) == 4
    for relative, expected in {**generated['使用資料SHA256'], **visual['画像SHA256']}.items():
        assert digest(ROOT / relative) == expected, relative
    for relative, expected in display['正式根拠SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    source = HERE / '公開前' / TITLE
    assert digest(source) == generated['HTML_SHA256']
    target = ROOT / 'アルゴリズム調査' / NAME
    assert not target.exists()
    serials = [int(p.name[:5]) for p in target.parent.iterdir() if p.is_dir() and re.match(r'^\d{5}_', p.name)]
    assert max(serials) == 97
    previous = {}
    for serial in range(86, 98):
        folder = next(target.parent.glob(f'{serial:05d}_*'))
        previous.update({str(p.relative_to(ROOT)): digest(p) for p in folder.rglob('*') if p.is_file()})
    target.mkdir()
    (target / TITLE).write_bytes(source.read_bytes())
    (target / '公開会計.json').write_bytes((WORK / 'analysis/比較結果.json').read_bytes())
    (target / '原因と実建玉の補足.json').write_bytes((WORK / 'analysis/説明補足.json').read_bytes())
    (target / '停止余裕と同入口の独立原因.json').write_bytes(cause_path.read_bytes())
    (target / '追加ナイトと全32の損益.json').write_bytes(ADDITIONAL.read_bytes())
    (target / '追加40口座の独立検算.json').write_bytes(ADDITIONAL_AUDIT.read_bytes())
    readme = f'''# 増玉の停止余裕と線保全の再検証

最初に[説明と全セッション損益]({TITLE})を開いてください。

短い結論、赤字頻度と赤字額の比較、手法の入口・途中・出口、元31セッション、追加ナイトと全32合計の順です。20条件を切替できます。詳しい条件と原因は折りたたみ内にあります。

新12条件は両商品とも初回1枚。追加後の停止余裕を初期幅の0.5／1／2倍で比較し、追加で停止線を寄せる方法と保全する方法を分けます。旧8対照と合わせ全20条件です。最大TOPIX8枚・日経16枚、利用上限は片方向10／20枚。手数料後、全玉をセッション内で返済します。実玉群と親は同じ収支の別集計であり、加算しません。

[公開会計](公開会計.json)に全20条件・全31損益、[原因と実建玉の補足](原因と実建玉の補足.json)に説明の根拠を保存しています。[停止余裕と同入口の独立原因](停止余裕と同入口の独立原因.json)は新しい5条件310口座の検算で、使用した資料と検査範囲を記録しています。再現コードと独立検査は[work/wave_v102](../../work/wave_v102)です。

全1240口座の会計を独立検算しています。独立原因の対象は同入口比較・固定1枚との実金融同値・新19列の門番です。表示には実玉群の相殺前損失を掲載し、親内の損失を隠しません。

元31は既知期間の再探索です。元31表を保持し、同じ固定20条件・同じ前16参考で確認した追加ナイトを別表へ載せています。[追加ナイトと全32損益](追加ナイトと全32の損益.json)は元31＋追加1の合算、[追加40口座の独立検算](追加40口座の独立検算.json)は追加1だけの検査です。元31の1240口座、追加1の40口座、合算1280口座の範囲を混同しません。

無取引を勝ちに含めず、少枚数によるリスク削減と黒字確度の改善を分けます。現在API取得と実注文は行っていません。毎セッションの安定収益と金額利益80%の調査は継続中です。
'''
    (target / 'README.md').write_text(readme, encoding='utf-8')
    # ----------------------------------------
    # 案内の最新リンクを更新し、過去の作業とリンクを保持する。
    root_readme = ROOT / 'README.md'
    text = root_readme.read_text(encoding='utf-8')
    latest = f'最新の調査は **[00098：増玉の停止余裕と線保全の再検証](アルゴリズム調査/{NAME}/{TITLE})** です。20条件・元31場の安定性と停止余裕を比較し、追加ナイトと全32合計を別表へ掲載。[読む順序](アルゴリズム調査/{NAME}/README.md)も参照してください。両銘柄の安定収益と金額利益80%への調査は継続中です。'
    text, count = re.subn(r'最新の調査は[^\n]+', latest, text, count=1)
    assert count == 1
    root_readme.write_text(text, encoding='utf-8')
    research_readme = target.parent / 'README.md'
    text = research_readme.read_text(encoding='utf-8').replace('**最新は00097の', '**00097の', 1)
    announcement = f'<!--00098案内開始-->\n**最新は00098の[説明と全セッション損益]({NAME}/{TITLE})。停止余裕と線保全の20条件を元31場で比較。追加ナイトと全32合計は別表で掲載。**\n\n[読む順序]({NAME}/README.md) · [元31公開会計]({NAME}/公開会計.json) · [追加1と全32]({NAME}/追加ナイトと全32の損益.json)。元31は既知期間です。\n<!--00098案内終了-->\n\n'
    anchor = '<!--00097案内開始-->'
    assert anchor in text
    research_readme.write_text(text.replace(anchor, announcement + anchor, 1), encoding='utf-8')
    index = target.parent / 'index.html'
    text = index.read_text(encoding='utf-8').replace('作業00097 · 最新', '作業00097', 1)
    article = f'<!--00098開始--><article class="task"><div class="number">作業00098 · 最新</div><h2>増玉の停止余裕と線保全の再検証</h2><p>20条件の元31場を赤字頻度・平均最大赤字で比較。追加ナイトと全32合計は同じ条件の別表へ掲載。</p><a class="primary" href="{NAME}/{TITLE}">説明と全セッション損益を開く</a> <a href="{NAME}/README.md">読む順序</a></article><!--00098終了-->\n'
    anchor = '<!--00097開始-->'
    assert anchor in text
    index.write_text(text.replace(anchor, article + anchor, 1), encoding='utf-8')
    for relative, expected in previous.items():
        assert digest(ROOT / relative) == expected, relative
    assert digest(target / TITLE) == generated['HTML_SHA256']
    proof = dict(全合格=True, 公開先=str(target.relative_to(ROOT)), 条件数=20, 全セッション数=32, 元31セッション数=31,
                 元31独立口座数=1240, 追加セッション数=1, 追加独立口座数=40, 全32合算口座数=1280,
                 HTML_SHA256=digest(target / TITLE), 旧86から97を不変保持=True,
                 旧資料SHA256=previous,
                 独立原因の使用範囲=cause['scope'],
                 検査根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in
                     (Path(__file__), HERE / '生成結果.json', HERE / '表示の独立検査.json',
                      HERE / '根担当の目視確認.json', cause_path, WORK / 'analysis/比較結果.json',
                      WORK / 'analysis/説明補足.json', ADDITIONAL, ADDITIONAL_AUDIT)})
    (HERE / '公開結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print('00098の説明・全31損益と案内を公開しました。旧86から97の成果は保持しました。', flush=True)


if __name__ == '__main__':
    main()

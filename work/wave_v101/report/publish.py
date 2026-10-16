"""全数会計・原因・表示と根の目視後に00097を公開し、旧成果を保持する。"""

import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
NAME = '00097_初回小枚数と利益で支える増玉の安定性'
TITLE = '小さく入り利益で増やす手法と全セッション損益.html'


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
    引数: なし。
    返り値: None。売買条件、会計、旧作業を変更しない。
    """
    generated = read(HERE / '生成結果.json')
    display = read(HERE / '表示の独立検査.json')
    visual = read(HERE / '根担当の目視確認.json')
    audit = read(WORK / 'audit/全20全31の増玉注文と親cohort及び全原板会計の独立検算.json')
    cause_path = WORK / 'review/根説明補足の親内損失と増玉及び予算超過と最悪場の独立反証.json'
    cause = read(cause_path)
    geometry_path = WORK / 'review/赤字親の初回利益と追加後停止距離及び予算内反復負けの独立原因.json'
    geometry = read(geometry_path)
    assert generated['全合格'] and display['全合格'] and visual['全合格']
    assert audit['合格'] and not audit['人工専用']
    assert cause.get('全合格', cause.get('合格')) is True
    assert geometry['全合格']
    explanation_path = WORK / 'analysis/説明補足.json'
    assert cause['SHA256'][str(explanation_path.relative_to(ROOT))] == digest(explanation_path)
    assert geometry['SHA256'][str(explanation_path.relative_to(ROOT))] == digest(explanation_path)
    assert generated['条件数'] == display['保存結果一致数'] == 20
    assert generated['口座数'] == display['保存会計口座数'] == audit['検査件数']['口座'] == 1240
    assert generated['HTML_SHA256'] == display['HTML_SHA256'] == visual['HTML_SHA256']
    assert visual['表示検査SHA256'] == digest(HERE / '表示の独立検査.json')
    assert len(display['画面']) == len(visual['画像SHA256']) == 4
    for relative, expected in {**generated['使用資料SHA256'], **visual['画像SHA256']}.items():
        assert digest(ROOT / relative) == expected, relative
    source = HERE / '公開前' / TITLE
    assert digest(source) == generated['HTML_SHA256']
    target = ROOT / 'アルゴリズム調査' / NAME
    assert not target.exists()
    serials = [int(p.name[:5]) for p in target.parent.iterdir() if p.is_dir() and re.match(r'^\d{5}_', p.name)]
    assert max(serials) == 96
    previous = {}
    for serial in range(86, 97):
        folder = next(target.parent.glob(f'{serial:05d}_*'))
        previous.update({str(p.relative_to(ROOT)): digest(p) for p in folder.rglob('*') if p.is_file()})
    target.mkdir()
    (target / TITLE).write_bytes(source.read_bytes())
    (target / '公開会計.json').write_bytes((WORK / 'analysis/比較結果.json').read_bytes())
    (target / '原因と実建玉の補足.json').write_bytes((WORK / 'analysis/説明補足.json').read_bytes())
    (target / '補足の独立照合.json').write_bytes(cause_path.read_bytes())
    (target / '停止幅と反復負けの独立原因.json').write_bytes(geometry_path.read_bytes())
    readme = f'''# 初回小枚数と利益で支える増玉の安定性

最初に[説明と全セッション損益]({TITLE})を開いてください。

短い結論、赤字頻度と赤字額の比較、手法の入口・途中・出口、全31セッションの順です。20条件を切替できます。詳しい条件と原因は折りたたみ内にあります。

初回1／2／4枚と、固定又は利益で支える倍増を比較しました。最大TOPIX8枚・日経16枚、利用上限は片方向10／20枚。手数料を含み、全玉をセッション内で返済します。追加した玉の損失を相殺で隠さず、実玉群と親の両会計を併記します。収支は同じなので加算しません。

[公開会計](公開会計.json)に全20条件・全31損益、[原因と実建玉の補足](原因と実建玉の補足.json)に増玉の実損益、予算超過、主と参考の最悪3赤字場の事実を保存しています。再現コードと独立検査は[work/wave_v101](../../work/wave_v101)です。

全1240口座の会計は独立検算済みです。説明補足を作った後の[独立照合](補足の独立照合.json)は496口座、[停止幅と反復負けの独立原因](停止幅と反復負けの独立原因.json)は310口座で一致しました。主の追加後停止余裕の中央値は初期幅の約39%／43%。主の負けは全てR0予算内で、予算を守るだけでは反復負けを防げませんでした。

全31は既知期間の再探索です。無取引を勝ちに含めず、少枚数によるリスク削減と黒字確度の改善を分けます。現在API取得と実注文は行っていません。毎セッションの安定収益と金額利益80%の調査は継続中です。
'''
    (target / 'README.md').write_text(readme, encoding='utf-8')
    # ----------------------------------------
    # 案内の最新リンクを更新し、過去の作業とリンクを保持する。
    root_readme = ROOT / 'README.md'
    text = root_readme.read_text(encoding='utf-8')
    latest = f'最新の調査は **[00097：初回小枚数と利益で支える増玉の安定性](アルゴリズム調査/{NAME}/{TITLE})** です。20条件・全31既知場の赤字頻度と平均・最大赤字、実玉群の損失と全場損益を比較。[読む順序](アルゴリズム調査/{NAME}/README.md)も参照してください。両銘柄の安定収益と金額利益80%への調査は継続中です。'
    text, count = re.subn(r'最新の調査は[^\n]+', latest, text, count=1)
    assert count == 1
    root_readme.write_text(text, encoding='utf-8')
    research_readme = target.parent / 'README.md'
    text = research_readme.read_text(encoding='utf-8').replace('**最新は00096の', '**00096の', 1)
    announcement = f'<!--00097案内開始-->\n**最新は00097の[説明と全セッション損益]({NAME}/{TITLE})。初回数量と増玉の20条件、全31場の赤字頻度・平均最大赤字と実玉群の損失を比較。**\n\n[読む順序]({NAME}/README.md) · [公開会計]({NAME}/公開会計.json)。全31は既知期間です。\n<!--00097案内終了-->\n\n'
    anchor = '<!--00096案内開始-->'
    assert anchor in text
    research_readme.write_text(text.replace(anchor, announcement + anchor, 1), encoding='utf-8')
    index = target.parent / 'index.html'
    text = index.read_text(encoding='utf-8').replace('作業00096 · 最新', '作業00096', 1)
    article = f'<!--00097開始--><article class="task"><div class="number">作業00097 · 最新</div><h2>初回小枚数と利益で支える増玉の安定性</h2><p>20条件を全31場で比較。最大利益より赤字頻度・平均最大赤字を優先し、追加した負け玉と全セッション損益も掲載。</p><a class="primary" href="{NAME}/{TITLE}">説明と全セッション損益を開く</a> <a href="{NAME}/README.md">読む順序</a></article><!--00097終了-->\n'
    anchor = '<!--00096開始-->'
    assert anchor in text
    index.write_text(text.replace(anchor, article + anchor, 1), encoding='utf-8')
    for relative, expected in previous.items():
        assert digest(ROOT / relative) == expected, relative
    assert digest(target / TITLE) == generated['HTML_SHA256']
    proof = dict(全合格=True, 公開先=str(target.relative_to(ROOT)), 条件数=20, 全セッション数=31,
                 HTML_SHA256=digest(target / TITLE), 旧86から96を不変保持=True,
                 検査根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in
                     (Path(__file__), HERE / '生成結果.json', HERE / '表示の独立検査.json',
                      HERE / '根担当の目視確認.json', cause_path, geometry_path)})
    (HERE / '公開結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print('00097の説明・全31損益と案内を公開しました。旧成果は保持しました。', flush=True)


if __name__ == '__main__':
    main()

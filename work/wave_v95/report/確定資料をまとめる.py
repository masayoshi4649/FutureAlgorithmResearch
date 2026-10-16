"""根担当が五画面を確認した後、公開に使う完了資料の指紋をまとめる。"""

import argparse
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
specification = importlib.util.spec_from_file_location('公開資料を確定する95', HERE / 'publish.py')
publisher = importlib.util.module_from_spec(specification)
specification.loader.exec_module(publisher)


def item(name: str, expected: dict) -> dict:
    """
    機能: 現在の完了資料を合格値とともに公開目録へ結ぶ。
    引数: name(str、95内の相対位置)、expected(dict、必須値)。
    返り値: dictは相対位置・指紋・公開時にも要求する値。
    """
    path = WORK / name
    value = publisher.read(path)
    for key, required in expected.items():
        assert value[key] == required, (name, key)
    return dict(path=str(path.relative_to(ROOT)), SHA256=publisher.sha(path), 必須値=expected)


def main() -> None:
    """
    機能: 実際の五画像目視の明示後だけ目視記録と公開確定指紋を保存する。
    引数: --五画像確認済み(bool)は根担当の実確認後に指定する。
    返り値: None。条件・損益・参考代表は変更しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--五画像確認済み', action='store_true')
    args = parser.parse_args()
    assert args.五画像確認済み, '五画像を目視する前に合格へしません'
    generated = publisher.read(HERE / '生成結果.json')
    display = publisher.read(HERE / '表示の独立検査.json')
    assert display['全合格'] and len(display['画面']) == 5
    assert generated['HTML_SHA256'] == display['HTML_SHA256'] == publisher.sha(publisher.MAIN)
    images = {str(Path(view['画像']).relative_to(ROOT)): publisher.sha(Path(view['画像']))
              for view in display['画面']}
    visual = dict(全合格=True, HTML_SHA256=generated['HTML_SHA256'], 確認画像SHA256=images,
                  確認内容='広幅・狭幅・全31場・安定性と前後・条件と原因の五画像を根担当が実目視。暗色・金額色・全行と合計・折返し・表内横スクロールを確認。')
    (HERE / '根担当の五画面目視.json').write_text(
        __import__('json').dumps(visual, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # ----------------------------------------
    # 正式な全範囲証跡の件数を確認し、人工検査を公開損益へ代用しない。
    full_name = 'audit/全38全31の新入口と四源反転及び全原板会計と安定性の独立検算.json'
    full = publisher.read(WORK / full_name)
    for key, required in {'口座': 2356, '商品期間集計': 608, '注文': 17398,
                          '決済親': 8699, '全原板行': 301017266}.items():
        assert full['検査件数'][key] == required
    descriptors = {
        '事前固定': ('事前固定.json', dict(正式新条件損益前固定=True, 全31既知=True, 主='P3_R3_N')),
        '前16参考': ('前16参考代表.json', dict(全合格=True, selected='P0_R1_S', 後15正式損益前選定=True)),
        '正式会計': ('analysis/比較結果.json', dict(全合格=True, 条件数=38, primary='P3_R3_N', selected='P0_R1_S')),
        '全範囲独立検算': (full_name, dict(合格=True, 人工専用=False, 検査件数=full['検査件数'])),
        '独立参考選定': ('engine_review/後15未作成の全38前16実親会計と安定順による独立参考選定.json',
                         dict(全合格=True, 条件数=38, 前16口座数=1216, 後15損益閲覧=0)),
        '独立原因会計': ('review/全38条件全31の独立親会計と安定性及び一軸経路分解.json',
                         dict(全合格=True, 口座=2356, 注文=17398, 親=8699, 商品期間群=608)),
        '独立原因状態': ('review/全38の直前完了親と四源再参加及び候補時刻移動の独立原因分解.json',
                         dict(全合格=True, 口座=2356)),
        '最悪場原板': ('review/主と事前参考及び旧追従の最悪3場原板と赤字救済及び大勝ち依存の独立反証.json',
                       dict(全合格=True, 口座=2356)),
        '説明補足': ('analysis/説明補足.json', dict(全合格=True, 正式全範囲独立検算完了=True,
                                                  独立原因検査完了=True, 売買及び会計の変更=0)),
    }
    manifest = dict(確定済み=True, 全31既知=True, 五画面根目視完了=True,
                    資料={name: item(*descriptor) for name, descriptor in descriptors.items()},
                    目標未達=True, API取得=0, 実注文=0)
    (HERE / '公開確定指紋.json').write_text(
        __import__('json').dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('五画面の実目視と正式全範囲の完了資料を確認しました。', flush=True)


if __name__ == '__main__':
    main()

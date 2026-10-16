"""七領域の完了証跡と現在の実装指紋を照合し、正式固定へ渡す。"""

import argparse
from pathlib import Path

import data
import research


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def binding(name: str, expected: dict) -> dict:
    """
    機能: 合格値と依存指紋を検査した一証跡を目録へ結ぶ。
    引数: name(str、95内の相対位置)、expected(dict、必須の完了値)。
    返り値: dictは資料の位置・内容SHA256・必須値。
    """
    path = (HERE / name).resolve()
    assert path.is_relative_to(HERE.resolve()) and path.is_file()
    proof = research.read(path)
    for key, value in expected.items():
        assert proof[key] == value, (name, key)
    for relative, expected_sha in proof.get('SHA256', {}).items():
        assert data.digest(ROOT / relative) == expected_sha, (name, relative)
    return dict(資料=str(path.relative_to(ROOT)), SHA256=data.digest(path), 必須値=expected)


def main() -> None:
    """
    機能: 全七領域の合格が保存されてから損益前の照合目録を生成する。
    引数: コマンド引数complete_audit_proof(str)は独立人工と終端の包括証跡。
    返り値: None。前後の正式結果がある場合又は不完了なら生成しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--complete-audit-proof', required=True)
    args = parser.parse_args()
    assert not (HERE / '事前固定.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    checks = {
        '全62LP窓と源対応': binding('audit/全62新LP窓と旧候補格子及び別執行原seq対応の独立入力検算.json',
                                  dict(合格=True, 正式95損益実行=0, 正式95損益閲覧=0)),
        '旧2対照全31完全一致': binding('engine_preflight/旧2数量対照の全31経済と状態の完全一致.json',
                                       dict(全合格=True, 口座数=124, 全旧信号配列一致数=4836)),
        '38人工と実反転境界': binding('engine_preflight/全38人工と旧経済及び直前損失反転の四源境界及び接頭一致.json',
                                      dict(全合格=True, 人工経路=152, 人工接頭一致=576)),
        '38実接頭部と未来不変': binding('engine_preflight/全38実入力の5場両市場と10接頭及び四源未来変形と候補許可の不変.json',
                                        dict(全合格=True, 短い実経路=380, 実接頭=3800, 完結新損益計算=0)),
        '4入口源の全62独立準備': binding('audit/4入口源全62の旧state保持と候補許可event及び22別源の独立純準備検算.json',
                                         dict(合格=True, 準備口座=248, 対応条件数=38)),
        '38設計の敵対的反証': binding('review_pre/38条件の入口と四源再参加の損益前反証.json',
                                      dict(人工全合格=True, 条件数=38, 独立純判定人工数=120)),
        '全38独立人工台帳と会計及び源復元': binding(args.complete_audit_proof,
                                                  dict(合格=True, 人工台帳=2432,
                                                       rootcontroller通常main終端=True,
                                                       独立full通常CLI終端保存及び再読込=True,
                                                       正式95損益実行=0, 正式95損益閲覧=0)),
    }
    # ----------------------------------------
    # 同価格同源の一致と別担当の候補検査も、全依存に保持する。
    extra = {
        '同値同源の旧候補null': binding('engine_preflight/価格同値同源の旧候補nullと演算境界及び旧資格分離と発火消費.json',
                                        dict(全合格=True, 同値同源候補完全一致=32)),
        '独立候補と演算の反証': binding('review_pre/全62入力の正常LP追従候補と旧板資格の独立反証.json',
                                        dict(全合格=True, 口座数=62, 人工数=20)),
        '根台帳の保存往復': binding('engine_preflight/全38人工の根ledgerとrun_one及び66列反転記録と疎復元の保存往復一致.json',
                                    dict(全合格=True, 人工条件=38, 人工口座=152, 正式新損益計算=0)),
        '独立前16選定の人工': binding('engine_review/独立前16選定の親会計と手算順位及び数値改変と段階拒否の人工.json',
                                      dict(全合格=True, 人工条件数=38, 人工前16口座数=1216,
                                           根score及びselect呼出=0, 正式結果閲覧=0)),
    }
    research.save(HERE / '前検証の照合目録.json', dict(
        全合格=True, 検査=checks, 補足=extra, 正式新損益未実行=True, 全31既知=True,
        主='P3_R3_N', 条件数=38, 現在API取得=0, 実注文=0))
    print('七領域の前検証が現在の指紋で一致しました。', flush=True)


if __name__ == '__main__':
    main()

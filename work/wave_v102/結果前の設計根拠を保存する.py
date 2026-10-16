"""既知の増玉損失原因を、停止余裕と線保全の結果前仮説へ接続する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path: Path) -> str:
    """
    機能: 読取だけで根拠ファイルの内容指紋を求める。
    引数: path (Path)。既知の資料又は結果前資料。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 101の独立損失原因と102の変更理由を正式新損益前に固定する。
    引数: なし。
    返り値: None。新手法の金融成功を認定せず資料を保存する。
    """
    assert not (HERE / '事前固定.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    prior = HERE.parent / 'wave_v101'
    paths = [prior / '事前固定.json', prior / 'analysis/比較結果.json',
             prior / 'analysis/説明補足.json',
             prior / 'review/根説明補足の親内損失と増玉及び予算超過と最悪場の独立反証.json',
             prior / 'review/赤字親の初回利益と追加後停止距離及び予算内反復負けの独立原因.json',
             prior / 'review/9月30日ナイトの同初回約定と異なる実出口の独立対照.json',
             prior / 'audit/全20全31の増玉注文と親cohort及び全原板会計の独立検算.json',
             HERE / '結果前の設計草案.json', HERE / '結果前の数理明確化.json',
             HERE / '初版catalog.py', HERE / '初版結果前の設計案.json',
             HERE / 'catalog.py', HERE / '結果前の設計案.json',
             HERE / '正式新損益前の主変更理由.json', HERE / '実装前の仕様明確化.json',
             HERE / 'セッション安定性の事前評価.json', HERE / '前検証目録.json',
             HERE / 'root_preflight/初期不足履歴の保持.json',
             HERE / '前検証目録を作る.py', Path(__file__)]
    plan = json.loads((HERE / '結果前の設計案.json').read_text(encoding='utf-8'))
    assert plan['正式新条件売買実行'] == 0 and plan['理論主'] == 'B1_T0_Q1_X1'
    record = dict(
        全合格=True,
        根拠の範囲='101の既知の増玉損失と、102の結果前変更理由。新条件の収益性を意味しない。',
        元の原因='101主の追加後余裕はTOPIX0.389S・日経0.429Sが中央値。TOPIX59/60、日経56/56追加は1S未満。赤字43/40親は全てR0内で、約定超過だけでは反復損失を説明できない。',
        仮説='増玉後に最低0.5/1/2Sの停止余裕を要求する。T1は当該行の通常追尾更新後の統合停止線も保全する。',
        主変更='T1の厳しさを独立純数理で確認し、正式損益を見る前にB1_T0を主へ変更。初版を保持し、20比較条件は変更していない。',
        対照='同じ初回1枚の増玉なしと旧1/2呼値増玉及び全量固定を保持し、単なる小枚数効果と新余裕効果を分ける。',
        安定性='最大利益より赤字頻度・赤字額を重視する。増玉しないだけの条件を新たな予測成功とはしない。',
        限界='入口の方向候補は変更していない。予約後の悪約定は現実の約定として計上する。全31場は既知であり、未見確認ではない。',
        正式102損益=0, API取得=0, 実注文=0,
        設計根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths})
    (HERE / '結果前の設計根拠.json').write_text(
        json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('101の増玉原因と102の停止余裕仮説を新正式損益前に結合しました。', flush=True)


if __name__ == '__main__':
    main()

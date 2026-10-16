"""100の損失分類を101の数量配分仮説へ接続し、結果前の根拠を保存する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path: Path) -> str:
    """
    機能: 根拠ファイルの現在の内容を指紋化する。
    引数: path (Path)。既存の根拠。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 既知の100の原因と101の仮説を、新正式損益前に束ねる。
    引数: なし。
    返り値: None。新条件の収益性を認定せずJSONを保存する。
    """
    assert not (HERE / '事前固定.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    prior = HERE.parent / 'wave_v100'
    explanation = json.loads((prior / 'analysis/説明補足.json').read_text(encoding='utf-8'))
    cause = explanation['cause_notes']['損失の内訳']
    assert 'TOPIXの赤字5親中3親' in cause and '日経7親中6親' in cause
    paths = [prior / '事前固定.json', prior / 'analysis/比較結果.json',
             prior / 'analysis/説明補足.json', prior / 'review/3正式レビューの独立原因要旨.json',
             prior / 'audit/全34全31の台帳会計と代表待機及び全原板の独立検算.json',
             HERE / '結果前の設計案.json', HERE / '実装前の仕様明確化.json',
             HERE / 'セッション安定性の事前評価.json',
             HERE / 'review_pre/20条件の予算固定増玉と費用及び予約競合の損益前独立反証.json',
             HERE / '前検証目録を作る.py', HERE / 'root_preflight/初期不足履歴の保持.json',
             Path(__file__)]
    paths += [HERE / name for name in (
        'audit/人工不合格_00001.json',
        'audit/初回人工の実追加未到達によるカバー不足.json',
        'audit/通常CLIの初回依存読取不足.json',
        'audit/通常CLI不合格_00001.json',
        'root_preflight/根の初回保存fixture不足.json',
        'root_preflight/固定読取の純数理schema不足.json',
        'review_pre/初版の20条件純数理レビュー.json')]
    initial_prefix = HERE / 'engine_review/初回保持_三代表の実増玉接頭とcohort及び自己相手LPとBBO未来不変.json'
    if initial_prefix.exists():
        paths.append(initial_prefix)
    record = dict(
        全合格=True, 根拠の範囲='100の既知の損失分類と、101の結果前仮説。新収益性の証明ではない。',
        元の原因=cause,
        仮説='最初の誤入口を小数量にし、実保有の現在利益と全玉停止余裕が追加を支える場合だけ増やす。',
        対照='旧全量と、同じ初回数量の固定枚数を両方残して、小数量効果を分離する。',
        相殺の対策='親と建玉群を併記し、金額80%は両基準で判定する。',
        限界='方向予測自体は変えない。R0は成行の実損失上限ではない。全31は既知。',
        接頭初回の扱い='依存helperの変更を跨いだ初回は保存記録。開始終端SHA付きの最終再実行を現在の検査に使う。',
        正式101損益=0, API取得=0, 実注文=0,
        設計根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths})
    (HERE / '結果前の設計根拠.json').write_text(
        json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('101の仮説と100の原因を新正式損益前に結合しました。', flush=True)


if __name__ == '__main__':
    main()

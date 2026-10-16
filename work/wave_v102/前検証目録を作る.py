"""停止余裕と線保全の現版検査を結び、不合格履歴は別に保持する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path: Path) -> dict:
    """
    機能: 保存済みの検査資料を読む。
    引数: path (Path)。UTF-8のJSONファイル。
    返り値: dict。記載された資料。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 内容を変更せず資料の指紋を取得する。
    引数: path (Path)。検査するファイル。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def binding(relative: str) -> dict:
    """
    機能: 現在の正証跡と、その資料が宣言する全依存を照合する。
    引数: relative (str)。102内の相対パス。
    返り値: dict。根相対パスと指紋。過去の失敗を合格へ変えない。
    """
    path = HERE / relative
    proof = read(path)
    status = proof.get('全合格', proof.get('合格'))
    if status is None:
        assert proof.get('純数理全合格') is True and proof.get('仕様確定合格') is True, relative
    else:
        assert status is True, relative
    for name, expected in proof.get('SHA256', {}).items():
        assert digest(ROOT / name) == expected, name
    return dict(資料=str(path.relative_to(ROOT)), SHA256=digest(path))


# ----------------------------------------


def failure_history() -> dict:
    """
    機能: 初回の検算器不足と実接頭カバー不足をFalseのまま結合する。
    引数: なし。
    返り値: dict。履歴束の根相対パスと指紋。旧依存を現版合格へ流用しない。
    """
    names = [
        'engine_preflight/初回境界fixtureの同格子改変失敗と原証拠未保持.json',
        'review_pre/独立局所検算器の初期記述と未知期待の不足保持.json',
        'engine_review/実接頭不合格_00001.json',
        'engine_review/カバー診断初回の外部package名衝突.json',
        'engine_review/補完結合の初回参照パス表記不足.json',
    ]
    names += sorted(str(p.relative_to(HERE)) for p in
                    (HERE / 'engine_review').glob('*起動*不合格*.json'))
    records = []
    for name in names:
        path = HERE / name
        proof = read(path)
        assert proof.get('全合格', proof.get('合格')) is False, name
        records.append(dict(資料=name, 当時判定=False, SHA256=digest(path),
                            原記録保持=True,
                            注意='原記録を正証跡へ書き換えない。原失敗source未保持の限界は原記録に従う。'))
    result = dict(
        全合格=False, 履歴数=len(records), 履歴=records,
        解釈='修正前のFalseと原記録を保持する。正しい現版の検査は別の正証跡だけで判定する。',
        正式102損益=0, API取得=0, 実注文=0,
        SHA256={str((HERE / name).relative_to(ROOT)): digest(HERE / name) for name in names})
    path = HERE / 'root_preflight/初期不足履歴の保持.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return dict(資料=str(path.relative_to(ROOT)), SHA256=digest(path))


def main() -> None:
    """
    機能: 正式新損益前に必要5検査、補足及び不合格履歴を固定する。
    引数: なし。
    返り値: None。未完又は指紋不一致があれば保存せず停止する。
    """
    assert not (HERE / '事前固定.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    mandatory = {
        '全20人工と停止余裕及び据置': 'audit/全20人工の独立初回と増玉及び停止と全原板会計.json',
        '旧8対照全496と経済null': 'audit/旧八対照の101全496口座と旧経済及び増玉支持の完全一致.json',
        '実入力因果不変': 'engine_review/実入力因果不変の補完.json',
        '結果前独立反証': 'review_pre/局所人工の新余裕と据置及び19列の独立反証.json',
        '独立監査人工CLI全8期間の終端': 'audit/人工40口座の独立通常CLIと全8期間及び根台帳の保存終端.json',
    }
    extra = {
        '予約競合と不利fillの独立境界': 'audit/余裕拒否後の継続と据置後の実fill悪化及び予約競合の独立境界.json',
        '独立純数理と絶対数量': 'audit/初回幅余裕と統合停止線据置の独立純数理.json',
        '主変更と保持した初版の独立結合': 'review_pre/新主T0と保持した初版及び20条件の損益前独立再結合.json',
        '結果前の数理実例': 'engine_preflight/停止線据置と初期幅余裕の結果前数理.json',
        '不変会計の継承': 'root_preflight/101不変会計と既人工検算の継承.json',
        '根の全20と19門番保存往復': 'root_preflight/全20人工の根台帳と実建玉群及び19門番の保存往復.json',
        'PythonとJITの全20自己検査': 'engine_preflight/全20人工の初期幅余裕と据置及び旧8対照とPythonJIT自己検査.json',
        '通常追尾と悪fill及び期限の自己境界': 'engine_preflight/余裕と据置の拒否及び不利実fillと通常追尾と未知期限場末の少数自己検査.json',
        '独立前16選定と不正段階拒否': 'review_pre/新しい102実装反証_選定の人工.json',
        '旧496の開始終端ソース不変': 'audit/旧496検査の開始終端ソース不変.json',
    }
    record = dict(
        全合格=True, 新正式損益未実行=True,
        検査={name: binding(path) for name, path in mandatory.items()},
        補足={name: binding(path) for name, path in extra.items()},
        不合格履歴={'検算器不足と実接頭カバー不足の原False保持': failure_history()},
        主='B1_T0_Q1_X1',
        数量の意味='初回絶対1枚。追加後の全玉停止余裕を初回固定幅で測る。上限はTOPIX10・日経20以内。',
        会計の範囲='実親と実建玉群の双方、全原板清算時価と注文毎費用を独立照合。未決済損失や相殺を隠さない。',
        実入力の範囲='固定代表と固定場の実原行接頭及び6未来改変。実際に追加した接頭の補完範囲は正証跡に従う。真の受信順を証明したものではない。',
        評価の範囲='31場は既知。人工CLIの8期間は同じ人工入力を再利用した保存と集計の検査で、実期間の収益性ではない。',
        選定の範囲='最大利益より両商品の共通上限で測る赤字RMS・黒字頻度・最大赤字を先に評価。無取引は勝ちにしない。',
        API取得=0, 実注文=0)
    (HERE / '前検証目録.json').write_text(
        json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('102の必要5検査・補足10と原False履歴を新正式損益前に結合しました。', flush=True)


if __name__ == '__main__':
    main()

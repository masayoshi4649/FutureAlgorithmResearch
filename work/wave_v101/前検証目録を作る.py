"""数量配分の必要検査と、修正前の不合格履歴を分けて固定する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path: Path) -> dict:
    """
    機能: 合否と依存指紋のJSONを読む。
    引数: path (Path)。既存資料。
    返り値: dict。保存された証跡。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: ファイル内容を変更せずSHA256を求める。
    引数: path (Path)。既存資料又はソース。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def binding(relative: str, passed: bool = True) -> dict:
    """
    機能: 現版の合格証跡又は保存された不合格を、合否を変えず結ぶ。
    引数: relative (str) は101内のパス、passed (bool) は期待する判定。
    返り値: dict。根相対パスと証跡SHA256。
    """
    path = HERE / relative
    proof = read(path)
    status = proof.get('全合格', proof.get('合格', proof.get('仕様確定合格')))
    assert status is passed, relative
    for name, expected in proof.get('SHA256', {}).items():
        assert digest(ROOT / name) == expected, name
    return dict(資料=str(path.relative_to(ROOT)), SHA256=digest(path))


# ----------------------------------------


def failure_history() -> str:
    """
    機能: 修正前のFalse資料を保持し、旧版の参照を現版の合格に流用しない。
    引数: なし。
    返り値: str。Falseのまま保存した履歴束の101相対パス。
    """
    relatives = [
        'audit/人工不合格_00001.json',
        'audit/初回人工の実追加未到達によるカバー不足.json',
        'audit/通常CLIの初回依存読取不足.json',
        'audit/通常CLI不合格_00001.json',
        'root_preflight/根の初回保存fixture不足.json',
        'root_preflight/固定読取の純数理schema不足.json',
        'review_pre/初版の20条件純数理レビュー.json',
    ]
    records = []
    for relative in relatives:
        path = HERE / relative
        proof = read(path)
        assert proof.get('全合格', proof.get('合格', proof.get('仕様確定合格'))) is False
        network = proof if 'API取得' in proof else proof['元初回の限定証跡']
        assert network['API取得'] == network['実注文'] == 0
        zero_names = ('正式101損益', '正式101損益実行', '正式売買の新規生成',
                      '新正式損益', '正式101損益実行数')
        assert any(proof.get(name) == 0 for name in zero_names), relative
        changed = []
        fingerprints = dict(proof.get('元初回の限定証跡', {}).get('SHA256', {}))
        fingerprints.update(proof.get('SHA256', {}))
        for name, expected in fingerprints.items():
            current = ROOT / name
            if not current.exists() or digest(current) != expected:
                changed.append(dict(資料=name, 当時SHA256=expected,
                                    現在SHA256=digest(current) if current.exists() else None))
        records.append(dict(資料=relative, 当時判定=False, 修正後に変わった旧参照=changed))
    result = dict(
        全合格=False, 履歴数=len(records), 履歴=records,
        解釈='各原JSONのFalseを保持。修正で変わった当時の参照は過去の記録であり、現版の合格検査には使わない。現版の正証跡は別に全依存を照合する。',
        正式101損益=0, API取得=0, 実注文=0,
        SHA256={str((HERE / name).relative_to(ROOT)): digest(HERE / name) for name in relatives})
    relative = 'root_preflight/初期不足履歴の保持.json'
    (HERE / relative).write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return relative


def main() -> None:
    """
    機能: 新正式損益前の必要5検査と補足及びFalse履歴を固定する。
    引数: なし。
    返り値: None。未完又は指紋不一致なら保存せず停止する。
    """
    assert not (HERE / '事前固定.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    mandatory = {
        '全20人工と予算固定増玉': 'audit/全20人工の独立初回と増玉及び停止と全原板会計.json',
        '旧全量二対照全124と経済null': 'audit/旧全量二対照の100全124口座と旧経済及び支持と上限の完全一致.json',
        '実入力因果不変': 'engine_review/三代表の実増玉接頭とcohort及び自己相手LPとBBO未来不変.json',
        '結果前独立反証': 'review_pre/新しい101実装反証_局所状態と現金及び未来.json',
        '独立監査人工CLI全8期間の終端': 'audit/人工40口座の独立通常CLIと全8期間及び根台帳の保存終端.json',
    }
    extra = {
        '追加競合と未知基準の独立境界': 'audit/追加の悪fillと資格悪化及び未知復帰と期限場末の独立境界.json',
        '純数理の結果前反証': 'review_pre/20条件の予算固定増玉と費用及び予約競合の損益前独立反証.json',
        '独立数理と絶対数量': 'audit/独立数理期待値と数量及び予約順の事前確認.json',
        '独立会計helperの未完親': 'audit/独立会計helperの四台帳と未完接頭の準備確認.json',
        '根の会計と損失隠し検出': 'root_preflight/複数実新規と全量返済の人工会計.json',
        '根の全20台帳保存往復': 'root_preflight/全20人工の根台帳と実建玉群及び固定予算追加状態の保存往復.json',
        'PythonとJITの数量会計自己検査': 'engine_preflight/全20人工の絶対初回数量と実cohort及び旧全量とPythonJIT自己検査.json',
        '実fill悪化と期限等の自己境界': 'engine_preflight/追加予約の不利実fillと期限及び未知基準と費用床の少数自己検査.json',
        '独立前16選定と不正段階拒否': 'review_pre/新しい101実装反証_選定の人工.json',
    }
    failed = failure_history()
    record = dict(
        全合格=True, 新正式損益未実行=True,
        検査={name: binding(path) for name, path in mandatory.items()},
        補足={name: binding(path) for name, path in extra.items()},
        不合格履歴={'7件の初期不足をFalseのまま保持': binding(failed, False)},
        数量の意味='初回絶対1/2/4枚。実約定だけのE/Q/Fで初回R0を保持。未約定利益を入れない。',
        会計の範囲='親・各実建玉群・全量返済一注文・全原板時価を突合。親内相殺だけで80%としない。',
        実入力の範囲='3代表24接頭と6未来群各24。独立原行管理・会計への接続。全特徴の原JSONL再抽出や真受信順の証明とはしない。',
        診断の範囲='growth70状態・74イベント・25建玉群・24親を保存。付随源は全口座、active/finalstopと最初触発は代表原行管理の範囲。',
        履歴の範囲='不合格原JSONは内容指紋で保存。当時の改修前ソース参照は現版検査に流用しない。',
        API取得=0, 実注文=0)
    (HERE / '前検証目録.json').write_text(
        json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('101の必要5検査・補足9・不合格履歴7を新正式損益前に結合しました。', flush=True)


if __name__ == '__main__':
    main()

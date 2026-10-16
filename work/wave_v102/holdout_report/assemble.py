"""元31場と追加一場を別掲したまま、不変20条件の全32会計を合算する。"""

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import socket
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SESSION = '2026-10-12_Night'
SYMBOLS = ('TOPIX', 'NK225')
ORIGINAL_AUDIT = WORK / 'audit/全20全31の増玉注文と親cohort及び全原板会計の独立検算.json'
ADDITIONAL_AUDIT = WORK / 'audit/追加ナイト全20の40口座と原板及び独立管理の検算.json'
DESTINATION = HERE / '追加ナイトと全32の損益.json'
PARENT_ADDITIVE = ('profit', 'loss', 'net', 'gross', 'fees', 'campaigns',
    'winning_campaigns', 'losing_campaigns', 'flat_campaigns',
    'winning_lots', 'losing_lots', 'flat_lots', 'lots')
COHORT_ADDITIVE = ('profit', 'loss', 'net', 'gross', 'fees', 'cohorts',
    'winning_cohorts', 'losing_cohorts', 'flat_cohorts',
    'winning_lots', 'losing_lots', 'flat_lots', 'lots')


def digest(path: Path) -> str:
    """
    機能: 使用する資料の内容指紋を一定メモリーで求める。
    引数: path(Path)は対象資料。
    返り値: strはSHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read(path: Path) -> dict:
    """
    機能: 指定されたJSON資料だけを読む。
    引数: path(Path)は固定仕様、正式終端証跡又は確定会計の位置。
    返り値: dictは保存された内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """
    機能: 担当する新しい合算資料領域だけへ保存する。
    引数: path(Path)、value(dict)は新規出力の位置と内容。
    返り値: None。完成物の上書き及び旧会計の変更を拒絶する。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 合算からの外部通信又は金融再生を拒絶する。
    引数: args(tuple)、kwargs(dict)は呼出し引数。
    返り値: None。常にRuntimeErrorを送出する。
    """
    raise RuntimeError('合算では新規の売買、選定及び通信を行いません')


def module(name: str, path: Path) -> object:
    """
    機能: 固有名で既存の会計関数だけを接続する。
    引数: name(str)、path(Path)は名前と位置。
    返り値: objectは読取モジュール。関数の会計規則は変更しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def same(left: object, right: object) -> None:
    """
    機能: 再集計値を既存の会計と許容誤差内で比較する。
    引数: left/right(object)は辞書、列、数値又は標準値。
    返り値: None。不一致は停止する。
    """
    if isinstance(left, dict):
        assert left.keys() == right.keys(), (left.keys(), right.keys())
        for name in left:
            same(left[name], right[name])
    elif isinstance(left, list):
        assert len(left) == len(right)
        for a, b in zip(left, right):
            same(a, b)
    elif isinstance(left, (float, int)) and not isinstance(left, bool):
        assert isinstance(right, (float, int)) and math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-5), (left, right)
    else:
        assert left == right, (left, right)


def stability(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """
    機能: 同一商品の赤字頻度、活動黒字率及び赤字平均最大を実円額で再計算する。
    引数: rows(list[dict])は確定した口座会計、symbol(str)、sessions(list[str])は対象場順。
    返り値: dictは金額ベースのセッション安定性。無取引を勝ちに数えない。
    """
    selected = [row for session in sessions for row in rows
                if row['symbol'] == symbol and row['session'] == session]
    assert len(selected) == len(sessions)
    active = [row for row in selected if row['campaigns'] > 0]
    positive = [row for row in active if row['net'] > 1e-5]
    negative = [row for row in active if row['net'] < -1e-5]
    zero = [row for row in active if abs(row['net']) <= 1e-5]
    losses = [-row['net'] for row in negative]
    return dict(session_count=len(selected), active_sessions=len(active),
                positive_sessions=len(positive), losing_sessions=len(negative),
                no_trade_sessions=len(selected)-len(active), flat_active_sessions=len(zero),
                positive_session_rate=len(positive)/len(active) if active else None,
                losing_session_rate=len(negative)/len(selected) if selected else None,
                active_losing_session_rate=len(negative)/len(active) if active else None,
                mean_losing_session_yen=float(np.mean(losses)) if losses else 0.,
                worst_session_loss_yen=max(losses, default=0.),
                losing_session_net_yen=-sum(losses),
                all_sessions_profitable=all(row['net'] > 1e-5 for row in selected),
                definition='同一商品の手数料後netで判定。赤字頻度の全場分母と活動場分母を併記。無取引は黒字へ含めない。')


def combine(accounting: object, rows31: list[dict], rows1: list[dict], sessions31: list[str]) -> dict:
    """
    機能: 元期間と追加場を別々に再集計し、その合算及び建玉群相殺前会計を検算する。
    引数: accounting(object)は既存会計、rows31/rows1(list[dict])、sessions31(list[str])は元場順。
    返り値: dict[str,dict]は商品別のknown31/additional1/all32/stability32。
    """
    assert SESSION not in sessions31 and len(sessions31) == len(set(sessions31))
    assert len(rows31) == len(sessions31) * 2 and len(rows1) == 2
    expected = {(session, symbol) for session in sessions31 for symbol in SYMBOLS}
    assert {(row['session'], row['symbol']) for row in rows31} == expected
    assert {(row['session'], row['symbol']) for row in rows1} == {(SESSION, symbol) for symbol in SYMBOLS}
    sessions32 = sorted([*sessions31, SESSION])
    rows = sorted([*rows31, *rows1], key=lambda row: (row['session'], row['symbol']))
    results = {}
    for symbol in SYMBOLS:
        known = accounting.aggregate(rows31, symbol, sessions31)
        additional = accounting.aggregate(rows1, symbol, [SESSION])
        combined = accounting.aggregate(rows, symbol, sessions32)
        for name in PARENT_ADDITIVE:
            same(combined[name], known[name] + additional[name])
        for name in COHORT_ADDITIVE:
            same(combined['cohorts'][name], known['cohorts'][name] + additional['cohorts'][name])
        for value in (known, additional, combined):
            same(value['net'], value['profit'] - value['loss'])
            same(value['net'], value['gross'] - value['fees'])
            for field in ('net', 'gross', 'fees', 'lots'):
                same(value[field], value['cohorts'][field])
        stable = stability(rows, symbol, sessions32)
        for name in ('session_count', 'active_sessions', 'positive_sessions', 'losing_sessions',
                     'no_trade_sessions', 'positive_session_rate', 'all_sessions_profitable'):
            same(stable[name], combined[name])
        best = combined['best_day']
        excluding = [row for row in rows if row['symbol'] == symbol and row['session'][:10] != best]
        same(combined['without_best_day'], dict(accounting.sum_totals(excluding),
             cohorts=accounting.sum_cohort_totals([row['cohorts'] for row in excluding])))
        results[symbol] = dict(known31=known, additional1=additional, all32=combined, stability32=stable)
    return results


def completed_guards(root_confirmed: bool) -> tuple[dict, dict, dict, dict]:
    """
    機能: 根の明示通知と二つの独立監査及び追加再生の終端を会計結果読取より前に要求する。
    引数: root_confirmed(bool)は明示CLIフラグ。
    返り値: tuple[dict,dict,dict,dict]は既知31監査、追加40監査、追加開始固定及び終端。
    """
    assert root_confirmed, '根の追加独立完了通知なしでは正式会計を読みません'
    start_path = WORK / 'holdout_results/追加再生前固定.json'
    end_path = WORK / 'holdout_results/正式追加再生の終端.json'
    assert all(path.exists() for path in (ORIGINAL_AUDIT, ADDITIONAL_AUDIT, start_path, end_path)), '元31独立1240又は追加独立40の正式終端が未完了です'
    original, additional, start, end = [read(path) for path in (ORIGINAL_AUDIT, ADDITIONAL_AUDIT, start_path, end_path)]
    assert original['合格'] is True and original['人工専用'] is False
    assert original['検査件数']['口座'] == 1240 and original['検査件数']['商品期間'] == 320
    assert additional['合格'] is True and additional['人工専用'] is False
    assert additional['対象'] == SESSION and additional['検査件数']['口座'] == 40
    assert additional['検査件数']['商品期間'] == 40 and additional['開始終端ソース一致']
    assert additional['追加による条件変更'] == additional['追加による参考再選択'] == 0
    assert additional['新正式売買生成'] == additional['API取得'] == additional['実注文'] == 0
    assert start['全合格'] and start['対象'] == [SESSION] and start['元31結果確定後']
    assert start['正式追加損益実行'] == start['追加損益による条件又は参考変更'] == 0
    assert end['全合格'] and end['条件数'] == 20 and end['口座数'] == 40 and end['対象'] == SESSION
    assert end['条件変更'] == end['参考変更'] == 0 and end['開始終端指紋一致']
    assert start['SHA256'] == end['開始SHA256'] == end['SHA256']
    return original, additional, start, end


def formal() -> None:
    """
    機能: 独立終端後だけ確定会計を再集計し、旧31と追加1を区別した全32合算を保存する。
    引数: なし。呼出し前にCLIの根完了通知を必ず確認する。
    返り値: None。条件、主、前16参考及び元31会計は変更しない。
    """
    original_audit, additional_audit, start, end = completed_guards(True)
    assert not DESTINATION.exists(), '完成合算は上書きしません'
    fixed_path, selected_path, analysis_path = (WORK / name for name in
        ('事前固定.json', '前16参考代表.json', 'analysis/比較結果.json'))
    fixed, selected, analysis = [read(path) for path in (fixed_path, selected_path, analysis_path)]
    assert len(fixed['全31']) == 31 and SESSION not in fixed['全31']
    assert fixed['全31既知'] and fixed['固定対象外の新追加場'] == SESSION
    assert selected['後15正式損益前選定'] and selected['全31既知']
    assert selected['固定SHA256'] == digest(fixed_path)
    assert analysis['全合格'] and analysis['全31既知']
    assert analysis['primary'] == fixed['主'] == start['主']
    assert analysis['selected'] == selected['selected'] == start['前16参考']
    conditions = fixed['条件']
    assert len(conditions) == 20 and conditions == analysis['catalog'] == start['条件']
    ids = [config['id'] for config in conditions]
    assert set(analysis['results']) == set(ids)
    result_paths = [WORK / 'holdout_results/results' / (ident + '.json') for ident in ids]
    assert {path.name for path in (WORK / 'holdout_results/results').glob('*.json')} == {path.name for path in result_paths}
    paths = [Path(__file__), HERE / 'selfcheck.py', WORK / 'accounting.py', fixed_path, selected_path, analysis_path,
             ORIGINAL_AUDIT, ADDITIONAL_AUDIT, WORK / 'holdout_results/追加再生前固定.json',
             WORK / 'holdout_results/正式追加再生の終端.json', *result_paths]
    assert all(path.exists() for path in paths)
    direct_sha = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    # ----------------------------------------
    # 既に終端独立監査が照合した全依存指紋を保持し、直接読取資料の現在指紋と結ぶ。
    inherited_sha = {}
    for label, source in (('元31固定', fixed['SHA256']), ('元31独立監査', original_audit['SHA256']),
                           ('追加開始固定', start['SHA256']), ('追加独立監査', additional_audit['SHA256'])):
        assert source, label
        for relative, wanted in source.items():
            if relative in inherited_sha:
                assert inherited_sha[relative] == wanted, (label, relative)
            inherited_sha[relative] = wanted
    for relative, actual in direct_sha.items():
        if relative in inherited_sha:
            assert actual == inherited_sha[relative], ('監査から直接使用までの変更', relative)
    sys.path.insert(0, str(WORK))
    research = module('追加一場合算だけの102根会計接続', WORK / 'research.py')
    research.strategy.play = deny
    research.strategy.ENGINE.execute = deny
    assert digest(WORK / 'accounting.py') == direct_sha[str((WORK / 'accounting.py').relative_to(ROOT))]
    results, checked = {}, 0
    for config, path in zip(conditions, result_paths):
        ident = config['id']
        extra = read(path)
        prior = analysis['results'][ident]
        assert prior['config'] == extra['config'] == config
        rows31, rows1 = prior['rows'], extra['rows']
        result = combine(research.accounting, rows31, rows1, fixed['全31'])
        for symbol in SYMBOLS:
            same(result[symbol]['known31'], prior['periods']['全31'][symbol])
            same(result[symbol]['additional1'], extra['periods']['追加ナイト1'][symbol])
            for key in ('session_count', 'active_sessions', 'no_trade_sessions', 'losing_sessions',
                        'positive_session_rate', 'mean_losing_session_yen', 'worst_session_loss_yen'):
                same(stability(rows1, symbol, [SESSION])[key], extra['stability'][symbol][key])
        results[ident] = result
        checked += len(rows31) + len(rows1)
    assert checked == 1280
    assert {str(path.relative_to(ROOT)): digest(path) for path in paths} == direct_sha
    output = dict(全合格=True, 条件数=20, primary=fixed['主'], selected=selected['selected'], session=SESSION,
                  sessions31=fixed['全31'], sessions32=sorted([*fixed['全31'], SESSION]),
                  元31口座数=1240, 追加口座数=40, 全32口座数=1280, catalog=conditions,
                  元31既知=True, 本調査で未評価だった追加確認場数=1,
                  results=results, 元31会計の再集計一致=True, 追加1会計の再集計一致=True,
                  元31と追加1の金額枚数合算一致=True, 追加による条件変更=0, 追加による参考再選択=0,
                  大勝ち日除外の定義='各商品の全32でnet最大の暦日を再計算し、その日付のデイとナイトを共に除外。元31除外と追加1除外の単純合算はしない。',
                  会計単位='親は全量返済単位、cohortsは各実新規の建玉群。G/Lは手数料後netの正負で別集計。利益玉と損失玉を親内で相殺した違いを保持。',
                  限界='元31場は既知データの探索。追加一場は本調査で未評価だった確認場であり、元31で固定した主と前16参考を変更しない。一場の成否を一般的な未知性能や全日安定の証明とはしない。',
                  独立証跡=dict(元31=str(ORIGINAL_AUDIT.relative_to(ROOT)), 追加1=str(ADDITIONAL_AUDIT.relative_to(ROOT))),
                  直接依存SHA256=direct_sha, 終端監査が照合した依存SHA256=inherited_sha,
                  SHA256={**inherited_sha, **direct_sha},
                  指紋検査の範囲='直接使用資料は本合算の開始終端で一致。その他は既終端監査が照合した指紋を保存し、全旧原本と全旧台帳の追加二重走査はしない。',
                  新規売買生成=0, API取得=0, 実注文=0)
    save(DESTINATION, output)
    print('全20条件の元31と追加1を別掲し、全32・1280口座の金額及び枚数合算が一致しました', flush=True)


def main(argv: list[str] | None = None) -> None:
    """
    機能: 明示通知又は人工モードだけを許可し、金融資料の読取範囲を分ける。
    引数: argv(list[str] | None)はCLI引数。Noneなら実引数を使う。
    返り値: None。明示通知なしでは既存損益結果を読まない。
    """
    parser = argparse.ArgumentParser(description='元31独立1240と追加独立40の終端後だけ全32を合算する')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--root-holdout-independent-complete', action='store_true')
    mode.add_argument('--artificial', action='store_true')
    args = parser.parse_args(argv)
    socket.socket.connect = deny
    socket.create_connection = deny
    if args.artificial:
        selfcheck = module('追加合算の小人工だけを確認する', HERE / 'selfcheck.py')
        selfcheck.check()
    else:
        completed_guards(args.root_holdout_independent_complete)
        formal()


if __name__ == '__main__':
    main()

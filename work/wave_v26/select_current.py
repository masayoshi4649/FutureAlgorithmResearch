"""反証後の候補選択方法を結果前に固定し、現在照合の対象を機械的に決める。"""

from __future__ import annotations

from datetime import datetime
import argparse
from pathlib import Path
from zoneinfo import ZoneInfo

import ensemble_runner as runner

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / 'wave_v25'
OLD = HERE.parent / 'wave_v23'


def plan() -> dict:
    """機能: 一次反証と無関係対照後の採用規則を先に固定する。

    引数: なし。返り値: 固定規則 (dict)。閾値は正式な統計検定ではない。
    """
    rules = {'候補条件': '第２反復の全一次反証を通過した候補のうち、事前選定された最大10対照対象だけ。',
             '乱数条件': '64seedの２方式とも、両銘柄の収支が候補以上のseedが3以下。各銘柄でPFが候補以上のseedも各6以下。',
             '規則の意味': '同じ既知期間での実用的なふるい分け。5%や10%の正式な有意確率とは解釈しない。',
             '順位': '第２反復の探索順位を維持。条件数や反証後の良い近傍へ置換しない。',
             '新候補数': '異なる信号思想の上位２件まで。首位を主候補とする。該当なしなら主候補なし。',
             '固定比較': ['F32__G08', 'D016__D065', 'P02__D065'],
             '現在取得': '選定後に各URL一回だけ。全候補同じスナップショット。現在収益による再選択・再最適化・再取得は禁止。',
             '既読境界': '2026-09-29T17:25:00+09:00',
             '途中損益': '実現利益/損失・含み損益・未返済枚数を分離。場末を捏造しない。17:25時点からの時価損益差も併記。'}
    path = HERE / '現在照合選抜の事前規則.json'
    if path.exists():
        fixed = runner.read(path)
        assert fixed['規則'] == rules
        assert fixed['コードSHA256'] == runner.digest(Path(__file__))
        return fixed
    fixed = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '規則': rules,
             'コードSHA256': runner.digest(Path(__file__))}
    runner.save(path, fixed)
    return fixed


def select() -> dict:
    """機能: 固定判定と順位から最大２候補を選び、固定比較３件とともに保存する。

    引数: なし。返り値: 現在照合対象 (dict)。現データは参照しない。
    """
    fixed_plan = plan()
    first = runner.read(HERE / '一次反証の結果.json')
    random = runner.read(HERE / '無関係対照の要約.json')
    passed = {x['candidate']['id'] for x in first if not x['first_stage_failures']}
    eligible, rejected = [], []
    for entry in random:
        candidate = entry['candidate']
        reasons = []
        if candidate['id'] not in passed:
            reasons.append('一次反証未通過')
        for case in entry['summary']:
            if case['両銘柄で候補以上の収支seed数'] > 3:
                reasons.append(f"発火限定{case['発火時刻限定']}:両銘柄収支の対照条件未達")
            for symbol, values in case['symbols'].items():
                if values['候補以上のPF_seed数'] > 6:
                    reasons.append(f"発火限定{case['発火時刻限定']}:{symbol}のPF対照条件未達")
        (rejected if reasons else eligible).append({'candidate': candidate, 'reasons': reasons})
    eligible.sort(key=lambda x: x['candidate']['id'])
    eligible.sort(key=lambda x: runner.score(x['candidate']), reverse=True)
    specs = runner.read(HERE / '探索条件の固定.json')
    chosen, families = [], set()
    for entry in eligible:
        candidate = entry['candidate']
        if candidate['signal_family'] in families:
            continue
        families.add(candidate['signal_family'])
        signal = next(x for x in specs['signals'] if x['id'] == candidate['signal_id'])
        management = next(x for x in specs['managers'] if x['id'] == candidate['manager_id'])
        chosen.append({'id': candidate['id'], 'name': signal['name'] + '／' + management['name'],
                       'signal': dict(signal, 実装元='多窓'), 'manager': management, '用途': '反証通過した新候補'})
        if len(chosen) == 2:
            break
    primary = chosen[0]['id'] if chosen else None
    old_specs = runner.read(PREVIOUS / '探索条件の固定.json')
    for identifier, source in [('F32', '既存板'), ('D016', '新規板'), ('P02', '価格P02')]:
        signal = next(x for x in old_specs['signals'] if x['id'] == ('D016' if identifier == 'P02' else identifier))
        manager_id = 'G08' if identifier == 'F32' else 'D065'
        management = next(x for x in old_specs['managers'] if x['id'] == manager_id)
        chosen.append({'id': identifier + '__' + manager_id, 'name': identifier + '固定比較',
                       'signal': dict(signal, 実装元=source), 'manager': management, '用途': '固定比較。今回の新候補とは別。'})
    output = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '主候補': primary,
              '候補': chosen, '候補再選択禁止': True, '適格候補': eligible, '対照不合格': rejected,
              '事前規則': fixed_plan, '現在データ取得済み': False}
    path = HERE / '現在照合候補の固定.json'
    if path.exists():
        old = runner.read(path)
        assert old['主候補'] == primary and old['候補'] == chosen
        return old
    runner.save(path, output)
    return output


def main() -> None:
    """機能: 選抜規則の固定と、反証完了後の対象選択を分けて実行する。

    引数: --prepare (bool)。返り値: なし (None)。通信しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    plan()
    if args.prepare:
        print('現在照合の選抜規則を固定。新探索の結果・現在価格は未参照。')
    else:
        result = select()
        print('主候補:', result['主候補'], '対象:', [x['id'] for x in result['候補']])


if __name__ == '__main__':
    main()

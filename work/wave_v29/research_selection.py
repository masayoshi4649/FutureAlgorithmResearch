"""第五反復の候補を、同じ入口の未保護基準と旧主案の両方で比較する。"""

from __future__ import annotations

from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent


def read(path: Path) -> object:
    """機能: UTF-8の保存済みJSONを読む。

    引数: path (Path)。返り値: 記録 (object)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def plan() -> dict:
    """機能: 新損益の閲覧前に、改善候補の判定規則を保存する。

    引数: なし。返り値: 固定規則 (dict)。
    """
    rules = {'前段': 'v27と同じ最低基準とv29の全一次反証、事前選定した乱数対照を通過する。',
             '比較基準': 'v27の凍結主案H019__D273。同一銘柄内の金額だけを比較し、銘柄間の円額は合算しない。',
             '改善': '両銘柄とも期間収支を主案の75%以上残し、含み損込み最大下落を主案の80%以下にする。少ない既知期間の実用目標であり有意確率ではない。',
             '同じ入口': '同じ入口のK000も両銘柄黒字かつDDが正であること。その各銘柄の収支75%以上・DD80%以下も満たす。入口変更だけの改善を利益保護の効果と呼ばない。',
             '波': '指定4波×両銘柄の8区間全てで、正方向ネット保有20分以上。目標適合であり未知成績ではない。',
             '乱数': '64seedの2方式とも、両銘柄収支が候補以上のseedが3以下、各銘柄PFが候補以上のseedが6以下。空・不足・重複の要約は拒否。',
             '順位': '上の条件を全て満たす候補だけ、事前の探索順位scoreを維持する。良い近傍値へ差し替えない。',
             '思想': '最大2案。EMA8/30と15/60を同じEMA思想にまとめ、EMA・価格差・高安突破・VWAP・回帰の異なる主方向から選ぶ。',
             '新しい照合': '現在APIは再取得しない。9/29ナイト21:00の保存スナップショットも再生に使わない。候補が残っても新たな未知検証待ち。',
             '通過なし': 'なしと報告し、閾値を緩めたり旧主案を改良成功と呼んだりしない。'}
    file = HERE / '研究候補選抜の事前規則.json'
    digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if file.exists():
        saved = read(file)
        assert saved['規則'] == rules and saved['コードSHA256'] == digest
        return saved
    result = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '規則': rules, 'コードSHA256': digest}
    file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def select() -> dict:
    """機能: 反証・波・無関係対照・元主案との比較を満たす研究候補を固定する。

    引数: なし。返り値: 候補と全棄却理由 (dict)。価格取得や売買再生を行わない。
    """
    import protection_runner as runner
    fixed_plan = plan()
    before = runner.read(HERE.parent / 'wave_v27' / '反証前の候補固定.json')
    base = next(c for c in before['上位30'] if c['id'] == 'H019__D273')
    all_candidates = {c['id']: c for c in runner.read(HERE / '全条件の期間集計.json.gz')}
    first = runner.read(HERE / '一次反証の結果.json')
    passed = {r['candidate']['id'] for r in first if not r['first_stage_failures']}
    random = runner.read(HERE / '無関係対照の要約.json')
    target = runner.read(HERE / '無関係対照前の候補固定.json')
    assert len(random) == len(target) and {r['candidate']['id'] for r in random} == {r['id'] for r in target}
    episodes = runner.read(HERE / 'episode_audit.json')
    wave_passed = {r['method'] for r in episodes['方法別要約'] if r['対象区間数'] == 8 and r['目安達成区間数'] == 8}
    frozen = runner.read(HERE / '探索条件の固定.json')
    signals, managers = {s['id']: s for s in frozen['signals']}, {m['id']: m for m in frozen['managers']}
    accepted, rejected = [], []
    for value in random:
        candidate, reasons = value['candidate'], []
        if candidate['id'] not in passed:
            reasons.append('一次反証未通過')
        if candidate['id'] not in wave_passed:
            reasons.append('指定8波の保有目安未達')
        modes = value['summary']
        assert len(modes) == 2 and {m['発火時刻限定'] for m in modes} == {False, True}
        for case in modes:
            assert case['試行数'] == 64 and set(case['symbols']) == {'TOPIX', 'NK225'}
            if case['両銘柄で候補以上の収支seed数'] > 3:
                reasons.append(f"乱数・発火限定{case['発火時刻限定']}で収支条件未達")
            for symbol, result in case['symbols'].items():
                if result['候補以上のPF_seed数'] > 6:
                    reasons.append(f"{symbol}の乱数PF条件未達・発火限定{case['発火時刻限定']}")
        for symbol in ('TOPIX', 'NK225'):
            own, reference = candidate['symbols'][symbol], base['symbols'][symbol]
            if own['net_yen'] < .75 * reference['net_yen'] - 1e-8:
                reasons.append(symbol + 'の主案収益75%維持未達')
            if own['drawdown_yen'] > .80 * reference['drawdown_yen'] + 1e-8:
                reasons.append(symbol + 'の主案下落20%削減未達')
            paired = all_candidates[candidate['signal_id'] + '__K000']['symbols'][symbol]
            if paired['net_yen'] <= 0 or paired['drawdown_yen'] <= 0:
                reasons.append(symbol + 'の同入口基準が黒字かつ正のDDではない')
            else:
                if own['net_yen'] < .75 * paired['net_yen'] - 1e-8:
                    reasons.append(symbol + 'の同入口収益75%維持未達')
                if own['drawdown_yen'] > .80 * paired['drawdown_yen'] + 1e-8:
                    reasons.append(symbol + 'の同入口下落20%削減未達')
        (rejected if reasons else accepted).append({'candidate': candidate, 'reasons': reasons})
    accepted.sort(key=lambda r: r['candidate']['id'])
    accepted.sort(key=lambda r: runner.score(r['candidate']), reverse=True)
    chosen, families = [], set()
    for entry in accepted:
        candidate = entry['candidate']
        spec = signals[candidate['signal_id']]
        kind = spec['params']['main_kind']
        family = 'EMA' if kind.startswith('ema') else kind
        if family in families:
            continue
        families.add(family)
        chosen.append({'id': candidate['id'], 'signal': dict(spec, 実装元='二入力階層'),
                       'manager': managers[candidate['manager_id']], 'name': candidate['id'], '思想': family})
        if len(chosen) == 2:
            break
    result = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '主候補': chosen[0]['id'] if chosen else None,
              '候補': chosen, '候補再選択禁止': True, '適格候補': accepted, '棄却': rejected,
              '事前規則': fixed_plan, '現在データ使用': False, '新しい未知検証': '未実施・今後の新データ待ち'}
    file = HERE / '研究候補の固定.json'
    if file.exists():
        saved = runner.read(file)
        assert saved['候補'] == chosen and saved['主候補'] == result['主候補']
        return saved
    runner.save(file, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    plan()
    print('研究候補の規則を結果前に固定。' if args.prepare else '研究主候補: ' + str(select()['主候補']), flush=True)

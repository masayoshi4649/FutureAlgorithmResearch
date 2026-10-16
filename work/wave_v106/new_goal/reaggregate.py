"""保存された会計だけを新しい金額・場損失基準で再集計する。売買は再生しない。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from statistics import mean, median


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'
SOURCES = (
    '公開会計.json', 'E01公開会計.json',
    'E01取引更新と損失予算の公開会計.json',
    '価格往復型と自動選択の公開会計.json', '直近位相の公開会計.json',
    '約定更新確認の公開会計.json', '保有中反対票の公開会計.json',
    '一呼値小利益の公開会計.json', '常設利確と成行返済の公開会計.json',
    '情報不足見送りの公開会計.json',
)


def fingerprint(path: Path) -> str:
    """
    機能: 保存ファイルの指紋を求める。
    引数: path（Path）指紋を求めるファイル。
    返り値: str。ファイル全体のSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(row: dict) -> dict:
    """
    機能: 二種類の公開会計から同じ集計項目を取り出す。
    引数: row（dict）元の一場・一商品の保存会計。
    返り値: dict。相殺前の利益損失と場収支、完結親数、費用。
    """
    result = dict(session=row['session'], symbol=row['symbol'])
    for english, japanese in (
        ('profit', '利益'), ('loss', '損失'), ('net', '収支'),
        ('campaigns', '親数'), ('fees', '費用'),
    ):
        result[english] = row[english] if english in row else row[japanese]
    assert result['profit'] >= 0 and result['loss'] >= 0
    assert abs(result['profit'] - result['loss'] - result['net']) < 0.000001
    assert result['campaigns'] >= 0
    assert result['campaigns'] or not any(result[key] for key in ('profit', 'loss', 'net', 'fees'))
    return result


def statistics(rows: list[dict]) -> dict:
    """
    機能: 未取引と黒字を区別し、金額割合・赤字頻度・平均黒字の補填力を計算する。
    引数: rows（list[dict]）一商品の対象場の正規化会計。
    返り値: dict。全場・活動場分母の割合、三条件の達否、半期間収支など。
    """
    profit = sum(row['profit'] for row in rows)
    loss = sum(row['loss'] for row in rows)
    green = [row['net'] for row in rows if row['net'] > 0]
    red = [-row['net'] for row in rows if row['net'] < 0]
    active = [row for row in rows if row['campaigns'] > 0]
    monetary_samples = [row['profit'] / (row['profit'] + row['loss'])
                        for row in active if row['profit'] + row['loss'] > 0]
    average_green = mean(green) if green else None
    worst_red = max(red, default=0)
    share = profit / (profit + loss) if profit + loss else None
    tests = dict(
        金額利益65以上=share is not None and share >= 0.65 - 1e-12,
        赤字全場20以下=len(red) <= len(rows) * 0.20 + 1e-12,
        最大赤字は平均黒字以下=average_green is not None and worst_red <= average_green + 1e-9,
    )
    active_red_ok = len(red) <= len(active) * 0.20 + 1e-12 if active else False
    return dict(
        profit=profit, loss=loss, net=profit-loss,
        profit_share=share, profit_factor=profit/loss if loss else None,
        sessions=len(rows), active=len(active), no_trade=len(rows)-len(active),
        green=len(green), red=len(red), flat_active=sum(row['net'] == 0 for row in active),
        red_all=len(red)/len(rows) if rows else None,
        red_active=len(red)/len(active) if active else None,
        mean_green=average_green, median_green=median(green) if green else None,
        worst_red=worst_red, mean_red=mean(red) if red else None,
        loss_recovery_ratio=worst_red/average_green if average_green else None,
        median_net=median(row['net'] for row in rows) if rows else None,
        active_median_net=median(row['net'] for row in active) if active else None,
        session_share_mean=mean(monetary_samples) if monetary_samples else None,
        session_share_mean_samples=len(monetary_samples),
        tests=tests, pass_all=all(tests.values()),
        active_red_test=active_red_ok,
        pass_active=all(tests.values()) and active_red_ok,
    )


def measure(rows: list[dict]) -> dict:
    """
    機能: 全33場、黒字上位3場除外、前後半を分離する。
    引数: rows（list[dict]）一商品の全33保存会計。
    返り値: dict。全場の基準判定と除外後の判定、除外場一覧。
    """
    ordered = sorted(rows, key=lambda row: row['session'])
    assert len(ordered) == len({row['session'] for row in ordered}) == 33
    top = sorted((row for row in ordered if row['net'] > 0),
                 key=lambda row: (-row['net'], row['session']))[:3]
    skipped = {row['session'] for row in top}
    remaining = [row for row in ordered if row['session'] not in skipped]
    full, tail = statistics(ordered), statistics(remaining)
    return dict(
        full=full, without_top3=tail,
        removed=[dict(session=row['session'], net=row['net']) for row in top],
        first16=statistics(ordered[:16]), last17=statistics(ordered[16:]),
        robust_pass=full['pass_all'] and tail['tests']['金額利益65以上']
                    and tail['tests']['最大赤字は平均黒字以下'],
        robust_active_pass=full['pass_active'] and tail['tests']['金額利益65以上']
                           and tail['tests']['最大赤字は平均黒字以下'],
        rows=ordered,
    )


def main() -> None:
    """
    機能: 保存10資料から重複IDを照合し、最新目標の全条件を再判定して保存する。
    引数: なし。対象は固定された既知33場の公開会計のみ。
    返り値: None。指紋・再集計・非金融範囲をJSONへ保存する。
    """
    output = HERE / '保存全候補の65比率と赤字頻度及び平均黒字補填力.json'
    assert not output.exists(), '同じ再集計の結果を上書きしない'
    sources, cases = [], {}
    display_count = 0
    for name in SOURCES:
        path = PUBLIC / name
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        assert data.get('全合格', True), (name, '保存表示の検査が不合格')
        sources.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=fingerprint(path)))
        configurations = {row['id']: row for row in data.get('configs', [])}
        for ident, case in data.get('cases', data.get('results', {})).items():
            display_count += 1
            rows = sorted((normalize(row) for row in case['rows']),
                          key=lambda row: (row['symbol'], row['session']))
            assert len(rows) == 66
            config = case.get('config') or case.get('case') or configurations.get(ident, {})
            if ident in cases:
                assert cases[ident]['rows'] == rows, (ident, name, '同IDの保存会計が不一致')
                cases[ident]['sources'].append(name)
                continue
            economic = json.dumps(rows, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')
            cases[ident] = dict(
                id=ident, config=config, rows=rows, sources=[name],
                ideal_reference=config.get('execution') == '旧現在値参考',
                saved_alias=case.get('saved_alias', False),
                alias_source_id=case.get('alias_source_id'),
                derived=case.get('derived', False),
                monetary_row_hash=hashlib.sha256(economic).hexdigest(),
            )
    # ----------------------------------------
    # 一致した会計を独立試行に数えず、銘柄別・同じ条件の両銘柄を判定する。
    monetary_groups = defaultdict(list)
    for ident, case in cases.items():
        monetary_groups[case['monetary_row_hash']].append(ident)
        case['symbols'] = {symbol: measure([row for row in case['rows'] if row['symbol'] == symbol])
                           for symbol in ('TOPIX', 'NK225')}
        case['both_full_pass'] = all(item['full']['pass_all'] for item in case['symbols'].values())
        case['both_robust_pass'] = all(item['robust_pass'] for item in case['symbols'].values())
        case['both_active_pass'] = all(item['full']['pass_active'] for item in case['symbols'].values())
        case['both_robust_active_pass'] = all(item['robust_active_pass'] for item in case['symbols'].values())
    eligible = {ident: case for ident, case in cases.items() if not case['ideal_reference']}
    per_symbol = {symbol: {
        'full_pass': [ident for ident, case in eligible.items() if case['symbols'][symbol]['full']['pass_all']],
        'robust_pass': [ident for ident, case in eligible.items() if case['symbols'][symbol]['robust_pass']],
        'active_pass': [ident for ident, case in eligible.items() if case['symbols'][symbol]['full']['pass_active']],
    } for symbol in ('TOPIX', 'NK225')}
    summary = dict(
        display_cases=display_count, distinct_ids=len(cases), eligible_ids=len(eligible),
        ideal_reference_ids=[ident for ident, case in cases.items() if case['ideal_reference']],
        economic_same_account_groups=[group for group in monetary_groups.values() if len(group) > 1],
        per_symbol=per_symbol,
        both_full_pass=[ident for ident, case in eligible.items() if case['both_full_pass']],
        both_robust_pass=[ident for ident, case in eligible.items() if case['both_robust_pass']],
        both_active_pass=[ident for ident, case in eligible.items() if case['both_active_pass']],
        both_robust_active_pass=[ident for ident, case in eligible.items() if case['both_robust_active_pass']],
    )
    result = dict(
        全合格=True, 作成日時=datetime.now(timezone(timedelta(hours=9))).isoformat(),
        定義=dict(金額割合='各完結取引群の費用後正損益P÷(P+負損益絶対値L)、全65%以上',
                  赤字頻度='場net<0の数/測定全場数<=20%、活動分母も別表示',
                  赤字補填='max(-赤字net)<=mean(黒字net)、場のP/黒字場数ではない',
                  除外='positive session net上位3を銘柄ごとに除外し再集計、取引規則ではない'),
        inputs=sources, source_sha256=fingerprint(Path(__file__)),
        summary=summary, cases=cases,
        新金融再生=0, 原板読込=0, NPZ読込=0, API取得=0,
        限界='00103の同じ既知33場を使った再集計。比較結果は独立標本ではない。PRICEは理想参照。無取引は黒字ではない。金融有効性の追加証拠ではない。',
    )
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                      encoding='utf-8', newline='\n')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()

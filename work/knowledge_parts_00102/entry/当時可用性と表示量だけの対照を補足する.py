"""既存入口数値の当時可用性と、表示量一軸の対照効果を補足する。"""

from pathlib import Path
import ast
import hashlib
import importlib.util
import json


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('入口知見抽出の共通部品', HERE / '保存された入口事象を分母別に抽出する.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def save(path: Path, value: object) -> str:
    """
    機能: 既存資料を上書きせず補足知見を保存する。
    引数: path(Path)、value(object)は保存先と内容。
    返り値: str。保存されたUTF-8資料のSHA256。
    """
    assert not path.exists(), path
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    path.write_text(text, encoding='utf-8')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def main() -> None:
    """
    機能: 入口003とJ1の保存値を確認し、表示量一軸の比較2件を追加する。
    引数: なし。
    返り値: None。入口再実行・金融再生・原本/NPZ/API読取をしない。
    """
    path = 'work/wave_v64/最大順行と入口採点.json'
    extent = helper.document(path)
    rows = [r for r in extent['rows'] if r['method'] == 'R3_DEPTH_C_quote' and r['symbol'] == 'NK225']
    helper.check('入口003分母23', len(rows), 23)
    helper.check('入口003順行到達22', sum(r['extent']['到達']['0.10']['順行到達'] for r in rows), 22)
    helper.check('入口003順行先着14', sum(r['extent']['到達']['0.10']['先着'] == 1 for r in rows), 14)
    helper.check('入口003逆行先着9', sum(r['extent']['到達']['0.10']['先着'] == -1 for r in rows), 9)
    peer_path = 'work/wave_v75/analysis/同じ新規機会での相手確認診断.json'
    peer = helper.document(peer_path)
    seen = set()
    for row in peer['明細']:
        key = row['セッション'], row['銘柄'], row['取引番号']
        assert key not in seen
        seen.add(key)
        stamp = row['共通代理時計']
        assert row['自参照代理時計'] < stamp - 5 and row['相手参照代理時計'] < stamp - 5
        assert stamp - 5 - row['自参照代理時計'] <= 30 and stamp - 5 - row['相手参照代理時計'] <= 30
        assert stamp <= row['発注代理時計'] <= stamp + 10
        assert row['自参照連番'] < row['発注判断連番']
        assert row['単独当時状態'] == row['建玉方向']
        assert (row['相手確認'] == '相手確認あり') == (row['共同当時状態'] == row['建玉方向'])
        assert row['発注判断行'] < row['実新規行'] <= row['実返済行']
    helper.check('J1全明細に当時時計・状態整合', len(seen), 142)
    source_path = 'work/wave_v75/analysis/same_opportunity.py'
    module = ast.parse((ROOT / source_path).read_text(encoding='utf-8'))
    function = next(v for v in module.body if isinstance(v, ast.FunctionDef) and v.name == 'past_label')
    helper.check('分類関数に出口・収支・将来値引数なし', [v.arg for v in function.args.args],
                 ['candidate', 'side', 'own', 'joint', 'grid', 'r', 'peer'])
    review = dict(全合格=True, 入口003=dict(分母=23, 場末順行到達=22, 対称順行先着=14, 逆行先着=9,
        注意='到達と先着を混ぜない。判断中値×0.1%を呼値切上げ。次原行以後を事後採点し、未来ピークを入口へ渡さない。'),
        J1=dict(保存実判断検査数=142, 条件='相手300秒の同方向3bp以上＋相手15秒非逆行。元S1の自市場条件は共通。',
            当時情報='分類関数は出口/収支を受け取らず、自己と相手の参照時計が判断格子-5秒より厳密に過去。142実判断の保存連番・時計・状態も整合。',
            限界='代理時計の当時可用性である。実受信時刻不明なので実配信の同時利用を保証しない。黒字率差は同じ売買の分類観測で純粋な因果効果ではない。'),
        粒度='入口001〜003/005〜007は複合条件の観測。004は同じS1の売買を相手条件で分けた一段細かい対照。',
        未収録='単独OFI・一般的な補充・距離重み板・MAクロス・VWAPだけを条件とした方向到達/先着確率。今回取得範囲で未整理であり、歴代一切未検証とは主張しない。',
        根拠=[helper.evidence(path, '/methods/2/summary/NK225/到達/0.10'), helper.evidence(peer_path, '/明細'),
              helper.evidence(source_path, function='past_label'), helper.evidence('work/wave_v75/inputs/core.py', function='asof_indices'),
              helper.evidence('work/wave_v75/signals.py', function='conditions')], 新金融再生=0)
    review_sha = save(HERE / '入口003とJ1当時可用性の第三者確認.json', review)

    # ----------------------------------------
    # 同じ共通仕様でuse_supplyだけが異なる、事前固定された2対照を抽出する。
    rules = []
    for family in ('C', 'R'):
        pairs = {}
        for suffix in ('PRICE', 'SUPPLY'):
            file = f'work/wave_v103/finance/results/{family}_{suffix}.json'
            pairs[suffix] = (file, helper.document(file))
        left, right = pairs['PRICE'][1]['config'], pairs['SUPPLY'][1]['config']
        helper.check(family + '独立変更use_supplyのみ',
            {k: v for k, v in left.items() if k not in ('id', 'use_supply')},
            {k: v for k, v in right.items() if k not in ('id', 'use_supply')})
        assert not left['use_supply'] and right['use_supply'] and not left['use_volume']
        measurements = []
        comparisons = []
        for period in ('前16', '後16', '全32'):
            for symbol in ('TOPIX', 'NK225'):
                a = pairs['PRICE'][1]['periods'][period][symbol]
                b = pairs['SUPPLY'][1]['periods'][period][symbol]
                scope = dict(期間='2026-09-21_Day〜2026-10-12_Night', セッション区分=period,
                             対象セッション数=32 if period == '全32' else 16, 既知データ=True,
                             枚数='各商品1枚、増玉なし', 共通='情報資格・別原行の価格段階・κ=1・peer確認・旧S/D30分出口',
                             相違='use_supplyだけFalse→True。use_volume=Falseは共通。')
                for suffix, stats in (('PRICE', a), ('SUPPLY', b)):
                    file = pairs[suffix][0]
                    measurements.append(helper.measurement(symbol, period + '・' + suffix + '・費用後黒字',
                        '表示量一軸対照の固定出口決済黒字率', stats['winning_campaigns'], stats['campaigns'],
                        '各方式で実際に約定した全完結親。入口時刻・取引集合は方式間で異なる。',
                        '実新規から旧S/D30分・場内返済の出口まで。', scope,
                        helper.evidence(file, f'/periods/{period}/{symbol}')))
                delta = b['net'] - a['net']
                measurements.append(dict(symbol=symbol, label=period + '・表示量条件追加による収支差',
                    kind='比較収支差・確率ではない', successes=None, total=None, value=delta, unit='円',
                    denominator='各方式の全実決済を商品別に合計。異なる商品を円で合算しない。',
                    horizon='同じ保存期間の旧固定出口まで。', scope=scope,
                    source=helper.evidence(pairs['SUPPLY'][0], f'/periods/{period}/{symbol}'),
                    calculation='SUPPLY.net - PRICE.net', control_source=helper.evidence(pairs['PRICE'][0], f'/periods/{period}/{symbol}')))
                comparisons.append(dict(period=period, symbol=symbol, price=dict(net=a['net'], trades=a['campaigns'], wins=a['winning_campaigns']),
                                        supply=dict(net=b['net'], trades=b['campaigns'], wins=b['winning_campaigns']), net_delta=delta))
        observed = ('表示量条件を足すと全32のTOPは48,936円改善、NKは47,238円悪化。どちらも収支赤字。' if family == 'C' else
                    '実数量回復条件を足すと全32のTOPは292,246円悪化、NKは13,832円改善。どちらも収支赤字。')
        mechanical = ('C_PRICEの別行による価格定着に、固定反対pの初期表示減少合計>=0.5Q0、新支持pの量>=0.5Q0を追加。' if family == 'C' else
                      'R_PRICEの別行による進行失敗・反対価格移動に、初期p表示減少>=0.5Q0、準備後の別行でp量が実増加かつ>=0.8Q0、新支持r量>=初回その側最良量×0.5を追加。')
        rule = helper.common_rule('入口_008' if family == 'C' else '入口_009',
            '価格の定着に表示数量の条件を足す' if family == 'C' else '進行失敗に実数量回復の条件を足す',
            '同じ価格パターンで、量の条件を要求した場合と要求しない場合を比べる。',
            mechanical + '双方use_volume=False・use_peer=True・κ=1。情報正常・期限・別行段階は共通。省略した門も情報正常の次別行へ分け、同原行多段通過は禁止。',
            observed, '表示数量の条件が銘柄共通で一律に改善するという仮説の反証。単独追加の数値結果として参照する。',
            ['切り替えた設定はuse_supply一つだが、初期減少・回復・新支持という複数の数量門を一式切り替える。各門個別の効果へは分解できない。',
             '実売買の時刻と取引集合が変わるため、同じ入口で数量だけを変えた純粋な因果効果ではない。',
             '取引数と損失規模の両方が変わる。収支差を方向予測確率の増減と呼ばない。',
             '共通の完全板・出来高などの入力資格は残るため、PRICEも一切板情報を使わない単純価格方式ではない。',
             '32場は既知。数量差は取消・約定・真の補充を同定せず、未知相場の保証はない。'], measurements,
            [helper.evidence(pairs[s][0], '/config') for s in ('PRICE', 'SUPPLY')] +
            [helper.evidence('work/wave_v103/catalog.py', function='catalog'), helper.evidence('work/wave_v103/数値設計補足06.json')])
        rule['comparisons'] = comparisons
        rules.append(rule)
    extra_sha = save(HERE / 'entry_component_rules.json', dict(rules=rules, 全合格=True, 新金融再生=0,
        scope='103の表示量一軸部品対照2件だけ。歴代の単独OFI等を網羅しない。', source_sha256=helper.READS))
    print(json.dumps(dict(全合格=True, 追加法則数=2, 当時可用性SHA256=review_sha,
        部品JSON_SHA256=extra_sha, source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()

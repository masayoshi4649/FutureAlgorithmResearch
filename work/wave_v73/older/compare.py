"""直近の旧ATR方式54保存結果を再会計し、観測値運転と固定気配置換を分けて比較する。"""

from collections import defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX', 'NK225')
VALUES = {'TOPIX':1000, 'NK225':10}
INITIAL = {'TOPIX':5, 'NK225':10}


def read(path: Path) -> dict:
    """機能: 旧作業の通常JSON又は圧縮JSONを読み取り専用で読み込む。

    引数: path(Path)。
    返り値: 保存された辞書(dict)。原本と旧成果を書き換えない。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def save(name: str, value: dict) -> None:
    """機能: 今回の旧方式比較領域へだけ日本語JSONを保存する。

    引数: name(str)、value(dict)。
    返り値: なし(None)。完成済み資料は上書きしない。
    """
    path = (HERE / name).resolve()
    assert path.is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def near(actual: float, expected: float) -> None:
    """機能: 保存会計と再計算会計を浮動小数誤差以内で照合する。

    引数: actual/expected(float)。
    返り値: なし(None)。差が1e-5円を超えた場合はAssertionError。
    """
    assert abs(actual - expected) < 1e-5, (actual, expected)


def fee(symbol: str, quantity: int) -> int:
    """機能: 片道注文料金を注文の枚数合計に対して切り捨てる。

    引数: symbol(str)、quantity(int)。
    返り値: TOPIXミニ41.8円又は日経マイクロ11円を用いた整数料金(int)。
    """
    return quantity * 418 // 10 if symbol == 'TOPIX' else quantity * 11


def observed_account(ledger: dict) -> dict:
    """機能: 観測値運転の全注文と全決済から独立に料金後損益を再集計する。

    引数: ledger(dict)。
    返り値: 決済明細・全玉組別の金額と数量の集計(dict)。
    """
    symbol = ledger['symbol']
    fees = 0
    position = 0
    maximum = 0
    campaign_charges = defaultdict(int)
    entries = {}
    for order, stored in zip(ledger['orders'], ledger['fees']):
        row, source, cid, side, quantity, price, reason, opened = order
        row, source, cid, side, quantity, opened = map(int, (row, source, cid, side, quantity, opened))
        assert 0 <= source < row and quantity > 0 and side in (-1, 1)
        charge = fee(symbol, quantity)
        assert charge == stored
        campaign_charges[cid] += charge
        fees += charge
        position += side * quantity
        maximum = max(maximum, abs(position))
        assert abs(position) <= INITIAL[symbol]
        if opened:
            entries[cid, row] = price
    assert position == 0 and maximum <= INITIAL[symbol]
    groups, parts = defaultdict(list), []
    for trade in ledger['trades']:
        cid = int(trade['組'])
        quantity = int(trade['枚数'])
        gross = trade['方向'] * quantity * (trade['返済値'] - trade['建値']) * VALUES[symbol]
        near(gross, trade['利益損失前'])
        near(gross - trade['手数料'], trade['収支'])
        near(entries[cid, int(trade['新規行'])], trade['建値'])
        groups[cid].append(trade)
        parts.append(trade)
    assert set(groups) == {int(c[0]) for c in ledger['cycles']}
    for cid, trades in groups.items():
        near(math.fsum(t['手数料'] for t in trades), campaign_charges[cid])
    nets = [math.fsum(t['収支'] for t in trades) for trades in groups.values()]
    result = dict(gross=math.fsum(t['利益損失前'] for t in parts), fees=fees,
        net=math.fsum(t['収支'] for t in parts),
        profit=math.fsum(t['収支'] for t in parts if t['収支'] > 0),
        loss=-math.fsum(t['収支'] for t in parts if t['収支'] < 0),
        campaign_profit=math.fsum(n for n in nets if n > 0),
        campaign_loss=-math.fsum(n for n in nets if n < 0),
        campaigns=len(nets), campaign_wins=sum(n > 0 for n in nets), campaign_losses=sum(n < 0 for n in nets),
        wins=sum(t['収支'] > 0 for t in parts), losses=sum(t['収支'] < 0 for t in parts),
        winning_lots=sum(t['枚数'] for t in parts if t['収支'] > 0),
        losing_lots=sum(t['枚数'] for t in parts if t['収支'] < 0), max_position=maximum)
    near(result['gross'] - result['fees'], result['net'])
    near(result['campaign_profit'] - result['campaign_loss'], result['net'])
    return result


def enrich(account: dict) -> dict:
    """機能: 利益合計対損失合計と一組平均の異なる指標を明示する。

    引数: account(dict)。
    返り値: 金額PF・利益に対する損失割合・一組平均損益比を加えた辞書(dict)。
    """
    value = dict(account)
    gain, loss = value['campaign_profit'], value['campaign_loss']
    value['money_PF'] = gain / loss if loss > 0 else None
    value['loss_to_profit'] = loss / gain if gain > 0 else None
    value['loss_share_of_absolute_PL'] = loss / (gain + loss) if gain + loss > 0 else None
    value['campaign_payoff'] = (gain/value['campaign_wins'])/(loss/value['campaign_losses']) if value['campaign_wins'] and value['campaign_losses'] else None
    value['campaign_win_rate'] = value['campaign_wins']/value['campaigns'] if value['campaigns'] else None
    return value


def rank(methods: list[dict], field: str = 'money_PF') -> dict:
    """機能: 同じモデル内で各銘柄の条件を金額指標順に並べる。

    引数: methods(list[dict])、field(str)。
    返り値: 両銘柄の全条件ランキング(dict[str,list[dict]])。
    """
    return {symbol: sorted([dict(id=m['id'], source=m['source'], name=m['name'],
                    **m['periods']['全28'][symbol]) for m in methods],
                    key=lambda row: (-(row[field] if row[field] is not None else -math.inf), -row['net'], row['id']))
            for symbol in SYMBOLS}


def main() -> None:
    """機能: 旧64・65の観測価格54結果と気配置換38結果を別会計で検算する。

    引数: なし。
    返り値: なし(None)。API取得・実注文・原本変更・旧成果変更は行わない。
    """
    fixed = read(ROOT / 'work/wave_v68/事前固定.json')
    sessions = fixed['全セッション']
    assert len(sessions) == 28
    methods, fingerprints, checked = [], {}, []
    seen = {}
    for folder in ('wave_v67', 'wave_v68'):
        for path in sorted((ROOT / 'work' / folder / 'observed').glob('*.json.gz')):
            data = read(path)
            assert data['model'] == 'observed' and len(data['rows']) == len(data['ledgers']) == 56
            assert sorted({r['session'] for r in data['rows']}) == sessions
            fingerprints[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
            lookup = {(r['session'], r['symbol']):r for r in data['rows']}
            for ledger in data['ledgers']:
                row = lookup[ledger['session'], ledger['symbol']]
                actual = observed_account(ledger)
                for field in actual:
                    if field != 'max_position':
                        near(actual[field], row[field])
                checked.append(dict(source=str(path.relative_to(ROOT)), session=ledger['session'],
                                    symbol=ledger['symbol'], 全玉会計一致=True, 全料金一致=True,
                                    終端保有ゼロ=True, 最大枚数=actual['max_position']))
            periods = {period:{symbol:enrich(account) for symbol,account in accounts.items()}
                       for period,accounts in data['periods'].items() if period in ('前16','後12','全28')}
            for symbol in SYMBOLS:
                subtotal = [r for r in data['rows'] if r['symbol'] == symbol]
                for field in ('campaign_profit','campaign_loss','net','fees','campaigns','campaign_wins','campaign_losses'):
                    near(sum(r[field] for r in subtotal), periods['全28'][symbol][field])
            method = dict(id=data['variant']['id'], source=str(path.relative_to(ROOT)),
                          name=data['variant']['name'], periods=periods, variant=data['variant'])
            if method['id'] in seen:
                previous = seen[method['id']]
                for period in ('前16','後12','全28'):
                    for symbol in SYMBOLS:
                        for field in ('campaign_profit','campaign_loss','net','fees','campaigns'):
                            near(previous['periods'][period][symbol][field], periods[period][symbol][field])
                previous.setdefault('同結果の重複資料', []).append(method['source'])
            else:
                seen[method['id']] = method
                methods.append(method)
    assert len(fingerprints) == 54 and len(methods) == 52
    main_rank = rank(methods)
    net_rank = rank(methods, 'net')
    # ----------------------------------------
    # 気配価格置換は固定台帳感度として別集計し、アルゴの気配再運転と混同しない。
    sensitivity_path = ROOT / 'work/wave_v68/review/気配価格置換の集計.json'
    sensitivity = read(sensitivity_path)
    sensitivity_methods = []
    for saved in sensitivity['methods']:
        path = ROOT / 'work/wave_v68/review/価格置換' / ('observed_' + saved['id'] + '.json.gz')
        data = read(path)
        assert data['sensitivity_only'] and not data['decisions_recomputed']
        assert len(data['accounts']) == 56
        for symbol in SYMBOLS:
            accounts = [a for a in data['accounts'] if a['symbol'] == symbol]
            assert len(accounts) == 28 and all(a['complete'] and not a['missing_orders'] for a in accounts)
            for account in accounts:
                cash = 0.
                position = 0
                for order in account['orders']:
                    assert order['available']
                    assert order['quote_seq'] <= order['order_seq'] and 0 <= order['age_seconds'] <= 30.000001
                    assert order['fee'] == fee(symbol, int(order['quantity']))
                    cash -= order['side'] * order['quantity'] * order['price'] * VALUES[symbol] + order['fee']
                    position += order['side'] * order['quantity']
                assert position == 0
                near(cash, account['net'])
                near(math.fsum(t['net'] for t in account['trades']), account['net'])
                near(math.fsum(c['net'] for c in account['campaigns']), account['net'])
            a = saved['periods']['全28'][symbol]
            groups = [c['net'] for account in accounts for c in account['campaigns']]
            near(math.fsum(x for x in groups if x > 0), a['campaign_profit'])
            near(-math.fsum(x for x in groups if x < 0), a['campaign_loss'])
            near(math.fsum(groups), a['net'])
        sensitivity_methods.append(dict(id=saved['id'], name=saved['name'], source=str(path.relative_to(ROOT)),
            periods={period:{symbol:enrich(a) for symbol,a in accounts.items()}
                     for period,accounts in saved['periods'].items()}))
        fingerprints[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(sensitivity_methods) == 38
    sensitivity_rank = rank(sensitivity_methods)
    save('旧ATR54条件の金額比較.json', dict(全合格=True, 保存結果54=54, 重複を除く条件52=52,
        sessions=sessions, 初回枚数=INITIAL, 名目片方向上限=fixed['片方向上限'], 実最大保有='全54結果で初回TOP5・NK10以下。',
        手数料=fixed['手数料'], 指標={'money_PF':'料金後の勝ち組利益合計／負け組損失合計',
            'loss_to_profit':'負け組損失合計／勝ち組利益合計。PFの逆数なので順位は一致する。',
            'campaign_payoff':'平均勝ち組損益／平均負け組損益。PFとは別指標。'},
        main=dict(model='observed_CurrentPrice', 方法='前行までに設定した線の発動を観測し、発動行のラージCurrentPriceで建値・返済線を再運転。',
                  rank=main_rank, net_rank=net_rank, methods=methods),
        quote_sensitivity=dict(model='固定注文価格置換', 主比較と別枠=True,
            方法='旧注文行・方向・数量を固定し、原板連番以下かつ時計以下の最終有効気配で買ask・売bidへ置換。最古30秒。',
            発動線と経路再計算=False, rank=sensitivity_rank, net_rank=rank(sensitivity_methods,'net'), methods=sensitivity_methods),
        v70比較の制限=['v70は気配によって条件成立を判断し、その次の有効観測気配で約定する。旧observedのラージ約定値とは基準が違う。',
            '旧方式の初回TOP5・NK10とv70のTOP10・NK20が違う。PFは枚数倍率の影響が小さいが金額総収支を直接優劣比較しない。',
            '旧方式はATR・EMAの入口と通常影時計を保持し、v70はティック入口と初回から3630秒の共通枠を使う。売買機会数と保有時間も異なる。',
            '固定気配置換では価格変更後の損切り線、利確線、2連敗判定、30分休止、次入口を再計算していない。quote再運転の期待成績とは呼ばない。',
            '両方式ともミニ／マイクロの仮想損益にラージ価格を使用する。実商品での数量約定は未検証。',
            '旧54結果は全28場だけで10/09デイを含まない。別に29場のT1L1_R01と混ぜない。',
            '全28は既知、全期間の後付けPF順位であり未見採用順位ではない。高いPFは95%の決済勝率を意味しない。'],
        独立再会計口座数=len(checked), SHA256=fingerprints, API取得=0, 実注文=0))
    save('旧ATR会計の照合.json', dict(全合格=True, 口座数=len(checked), 検査=checked, API取得=0, 実注文=0))
    for symbol in SYMBOLS:
        print(symbol, '観測価格PF上位', [(r['id'],r['money_PF'],r['net']) for r in main_rank[symbol][:3]])
        print(symbol, '固定気配置換PF上位', [(r['id'],r['money_PF'],r['net']) for r in sensitivity_rank[symbol][:3]])


if __name__ == '__main__':
    main()

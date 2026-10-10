"""保存済みの比較結果から、事前基準・週順選定・現在確認候補を評価する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')
WEEKS = ('2026-09-21', '2026-09-28', '2026-10-05')


def load(branch: str) -> dict:
    """機能: 指定枝の保存結果を読む。

    引数: branch(str) はmedium又はgrid。返り値: 全結果(dict)。
    """
    data = json.loads((HERE / branch / '売買結果.json').read_text(encoding='utf-8'))
    if branch == 'medium':
        return data
    lookup = {(m['condition_id'], m['price_mode']): m for m in data['methods']}
    normalized = []
    for source in data['methods']:
        if source['price_mode'] != 'quote':
            continue
        method = dict(source, accounts=[])
        for mode, prefix in (('quote', ''), ('mid', 'mid_'), ('passive', 'passive_')):
            variant = lookup[(source['condition_id'], mode)]
            for account in variant['accounts']:
                method['accounts'].append(dict(account, price_mode=mode,
                    profit=account['closed_net_profit'], loss=account['closed_net_loss']))
            method[prefix + 'summary'] = {s: dict(v, profit=v['closed_net_profit'], loss=v['closed_net_loss'])
                                          for s,v in variant['summary'].items()}
            method[prefix + 'weeks'] = {s: {w: dict(v, profit=v['closed_net_profit'], loss=v['closed_net_loss'])
                                           for w,v in weeks.items()} for s,weeks in variant['weeks'].items()}
        normalized.append(method)
    assert len(normalized) == 40
    return dict(data, methods=normalized)


def score(summary: dict) -> float:
    """機能: 利益損失比を順位に使える数値へ変換する。

    引数: summary(dict) は手数料控除済みの取引集計。返り値: PF(float)。
    """
    if summary['loss']:
        return summary['profit'] / summary['loss']
    return 1e12 if summary['profit'] > 0 else 0.


def aggregate(accounts: list[dict]) -> dict:
    """機能: 注文会計と完了取引会計を別々に加算し、期間を再集計する。

    引数: accounts(list[dict]) は同じ銘柄・価格方式の口座。
    返り値: 純益、取引純利益/損失、枚数、活動数と比率(dict)。
    """
    out = {key: sum(a[key] for a in accounts) for key in
           ('gross_pnl', 'gross_profit', 'gross_loss', 'fees', 'net', 'profit', 'loss',
            'cycles', 'win_qty', 'loss_qty', 'flat_qty')}
    out['sessions'] = len(accounts)
    out['active_sessions'] = sum(a['cycles'] > 0 or len(a['orders']) > 0 for a in accounts)
    out['positive_sessions'] = sum(a['net'] > 0 for a in accounts)
    out['without_best'] = out['net'] - max((a['net'] for a in accounts), default=0.)
    out['pf'] = out['profit'] / out['loss'] if out['loss'] else None
    win = out['profit'] / out['win_qty'] if out['win_qty'] else None
    loss = out['loss'] / out['loss_qty'] if out['loss_qty'] else None
    out['payoff'] = win / loss if win is not None and loss else None
    return out


def method_accounts(method: dict, symbol: str, weeks: tuple | list = WEEKS, mode: str = 'quote') -> list[dict]:
    """機能: 銘柄・価格方式・週を固定して口座を抜き出す。

    引数: method(dict)、symbol(str)、weeks(tuple|list)、mode(str)。返り値: 対象口座(list[dict])。
    """
    return [a for a in method['accounts'] if a['symbol'] == symbol and a['price_mode'] == mode and a['week'] in weeks]


def screen(method: dict) -> dict:
    """機能: 結果前に決めた共通安定基準と損小利大基準を判定する。

    引数: method(dict)。返り値: 銘柄別と共通の判定(dict)。
    """
    symbols = {}
    for symbol in SYMBOLS:
        value = aggregate(method_accounts(method, symbol))
        checks = dict(全期間純益正=value['net'] > 0,
                      三週区分全て純益正=all(aggregate(method_accounts(method, symbol, [w]))['net'] > 0 for w in WEEKS),
                      最大黒字場除外正=value['without_best'] > 0,
                      取引場8以上=value['active_sessions'] >= 8,
                      完了取引20以上=value['cycles'] >= 20)
        symbols[symbol] = dict(安定基準=all(checks.values()), 損小利大=(value['payoff'] or 0) > 1, 条件=checks)
    return dict(銘柄別=symbols, 共通安定=all(v['安定基準'] for v in symbols.values()),
                共通安定かつ損小利大=all(v['安定基準'] and v['損小利大'] for v in symbols.values()))


def choose(methods: list[dict], weeks: tuple | list, minimum: int, allow_negative: bool) -> dict | None:
    """機能: 先行期間だけの両銘柄PFで同一条件を選定する。

    引数: methods(list[dict])、weeks(tuple|list)、minimum(int)、allow_negative(bool)。
    返り値: 選定ID・損益状態・評価値(dict|None)。将来週は参照しない。
    """
    evaluated = []
    for method in methods:
        values = {s: aggregate(method_accounts(method, s, weeks)) for s in SYMBOLS}
        if any(v['cycles'] < minimum for v in values.values()):
            continue
        positive = all(v['net'] > 0 for v in values.values())
        evaluated.append(dict(id=method['id'], profitable_both=positive, score=min(score(v) for v in values.values()),
                              training_net={s: v['net'] for s, v in values.items()}))
    positive = [v for v in evaluated if v['profitable_both']]
    eligible = positive if positive else evaluated if allow_negative else []
    return sorted(eligible, key=lambda v: (-v['score'], v['id']))[0] if eligible else None


def main() -> None:
    """機能: 全保存結果の基準判定と週順選定を保存し、現在取得前の候補を固定する。

    引数: なし。返り値: なし(None)。ネットワークへ接続しない。
    """
    output, current, hashes = {}, {}, {}
    for branch in ('medium', 'grid'):
        data = load(branch)
        methods = data['methods']
        hashes[branch] = hashlib.sha256((HERE / branch / '売買結果.json').read_bytes()).hexdigest()
        checks = {m['id']: screen(m) for m in methods}
        sequential = []
        for training, testing in [(WEEKS[:1], WEEKS[1]), (WEEKS[:2], WEEKS[2])]:
            chosen = choose(methods, training, 10, False)
            selected = next((m for m in methods if chosen is not None and m['id'] == chosen['id']), None)
            sequential.append(dict(先行週=list(training), 適用週=testing, 選定=chosen,
                翌週成績={s: aggregate(method_accounts(selected, s, [testing])) for s in SYMBOLS} if selected else None))
        current[branch] = choose(methods, WEEKS, 20, True)
        output[branch] = dict(条件数=len(methods), 基準判定=checks,
            共通安定候補=[k for k,v in checks.items() if v['共通安定']],
            共通安定かつ損小利大候補=[k for k,v in checks.items() if v['共通安定かつ損小利大']],
            共通黒字数=sum(all(m['summary'][s]['net'] > 0 for s in SYMBOLS) for m in methods),
            週順選定=sequential, 現在確認候補=current[branch])
    evidence = dict(結果=output, source_sha256=hashes,
                    解釈='全25場は既知資料。週順選定も真の未知検証ではない。主quoteの候補を価格仮定の違う参考結果で差し替えない')
    (HERE / '事前基準と週順選定.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    folder = HERE / 'live'
    folder.mkdir(exist_ok=True)
    target = folder / '確認候補固定.json'
    frozen = dict(selected=current, source_sha256=hashes,
                  frozen_at=datetime.now(timezone(timedelta(hours=9))).isoformat(),
                  注記='共通黒字がなければ赤字の参考候補。現セッション取得後の入替えはしない')
    if target.exists():
        old = json.loads(target.read_text(encoding='utf-8'))
        assert old['selected'] == current and old['source_sha256'] == hashes, '現在確認前の選定が変更されています'
    else:
        target.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({b:{k:v for k,v in value.items() if k != '基準判定'} for b,value in output.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()

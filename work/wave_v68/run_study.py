"""同じ初回枚数のまま、失敗玉整理と料金後休止の損失削減を比較する。"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import socket

import numpy as np

import risk_replay as replay

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def save(path: Path, value: object) -> None:
    """機能: 今作業内に有限JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf8')
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)


def freeze() -> dict:
    """機能: 候補・時間順比較・損失低減の選定規則を今回再生前に固定する。

    引数: なし。返り値: 事前固定(dict)。
    """
    old = replay.previous.read(ROOT / 'work/wave_v67/事前固定.json')
    files = [HERE / name for name in ('risk_replay.py', 'loss_engine.py', 'loss_shadow.py', 'build_engine.py', 'run_study.py')]
    fixed = dict(条件=replay.catalog(), 全セッション=old['全セッション'], 前16=old['前16'], 後12=old['後12'],
        初回枚数=old['初回枚数'], 片方向上限=old['片方向上限'], 手数料=old['手数料'], 円倍率=old['円倍率'],
        約定='発動行のラージ観測値で建値・返済線を全再運転。未来価格・同じ行で新設した線へ遡らない。',
        損失制御='実玉の初回建値・固定ATR・現在までの最大順行・新しく公開した逆行を使用。半減は一回、復元なし。全返済は予約の次行。',
        優先順='元の返済線→実玉予算返済→早期全返済→減量。元返済が発動した場合は保留の早期整理を取り消す。',
        時計='全条件で通常影の新規時計を維持。早期全返済しても元時計終了+5分まで再参加しない。休止は実組が完了した当行までの料金後損益で判定する。',
        実予算='A50だけ初回数量×ATRの0.5倍を料金込みで監視。Rの集計分母は全条件1ATR。その他は元の料金前1ATR予算を維持。',
        選定='前16のみ。各銘柄で対応元方式に対し負け組損失合計10%以上削減、勝ち組利益80%以上・収支80%以上・活動場80%以上・組数70%以上維持、純黒字、1枚平均勝負比1超、場内最大下落が基準の110%以下。両銘柄合格なら弱い側の組損失削減率を最大化。同率は弱い側収支維持率、ID順。該当なしなら選定なし。',
        評価='部分決済の勝敗と、初回から全返済までの組勝敗を別集計。単に減量しただけの結果や無取引を改善としない。',
        既知性='全28は既知。後12の診断も仮説立案に用いた。前半選択・後半再確認は時間順ストレス試験であり完全な未見検証ではない。',
        API取得数=0, 実注文数=0,
        実装SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        前作業固定SHA256=hashlib.sha256((ROOT / 'work/wave_v67/事前固定.json').read_bytes()).hexdigest())
    target = HERE / '事前固定.json'
    if target.exists():
        assert replay.previous.read(target) == fixed
    else:
        save(target, fixed)
    return fixed


def enrich(row: dict, ledger: dict, equity: np.ndarray) -> None:
    """機能: 最大組損失・組平均損失と同時含み込み下落を会計へ追加する。

    引数: row/ledger(dict)、equity(ndarray)。返り値: なし(None)。
    """
    grouped = [sum(t['収支'] for t in ledger['trades'] if t['組'] == int(c[0])) for c in ledger['cycles']]
    row['max_campaign_loss'] = max((max(0., -v) for v in grouped), default=0.)
    row['average_campaign_loss'] = row['campaign_loss'] / max(1, row['campaign_losses'])
    row['average_losing_lot'] = row['loss'] / max(1, row['losing_lots'])
    row['controlled_exits'] = sum(t['理由'] in (50, 51, 52) for t in ledger['trades'])
    ledger['equity_checkpoints'] = [[float(equity[0])], [float(equity[-1])]]


def run(ids: list[str]) -> None:
    """機能: 固定条件を観測価格で再生し、両基準の注文完全一致も確認する。

    引数: ids(list[str])。返り値: なし(None)。
    """
    fixed = freeze()
    replay.base_replay.integration.reference.initialize()
    inputs, _, _ = replay.previous.load_inputs()
    models = {k: replay.base_replay.gate.model(r) for k, r in inputs.items()}
    ema = {k: replay.ema_columns(k, r, models) for k, r in inputs.items()}
    originals = {base: replay.previous.read(ROOT / 'work/wave_v67/observed' / (base + '.json.gz')) for base in ('E01', 'R01')}
    baseline_variants = {v['id']: v for v in replay.base_replay.catalog()}
    for variant in replay.catalog():
        if ids and variant['id'] not in ids:
            continue
        target = HERE / 'observed' / (variant['id'] + '.json.gz')
        if target.exists():
            print(variant['id'], '保存済み', flush=True)
            continue
        rows, ledgers = [], []
        original_ledgers = {(l['session'], l['symbol']): l for l in originals[variant['base']]['ledgers']}
        for key, ready in sorted(inputs.items()):
            columns, valid = replay.previous.columns_for(baseline_variants[variant['base']], key, ready, models)
            actual = replay.play(variant, ready, columns, valid, ema[key])
            result, _, _, config = actual
            if variant['id'] in ('E01', 'R01'):
                np.testing.assert_array_equal(result['orders'], np.asarray(original_ledgers[key]['orders']).reshape(result['orders'].shape))
            row, ledger, equity = replay.previous.account(ready, result, config)
            enrich(row, ledger, equity)
            ledger['loss_control'] = variant['control']
            ledger['risk_events'] = result['risk_events'].tolist()
            for order in result['orders']:
                assert 0 <= int(order[1]) < int(order[0]) < len(ready['last'])
            assert row['max_long'] <= config['initial_qty'] and row['max_short'] <= config['initial_qty']
            rows.append(row)
            ledgers.append(ledger)
            del actual, result, equity
        periods = {}
        for label, names in [('前16', fixed['前16']), ('後12', fixed['後12']), ('全28', fixed['全セッション'])]:
            periods[label] = {}
            for symbol in ('TOPIX', 'NK225'):
                account = replay.previous.aggregate(rows, symbol, names)
                subset = [r for r in rows if r['session'] in names and r['symbol'] == symbol]
                account['max_campaign_loss'] = max((r['max_campaign_loss'] for r in subset), default=0.)
                account['average_campaign_loss'] = account['campaign_loss'] / max(1, account['campaign_losses'])
                account['average_losing_lot'] = account['loss'] / max(1, account['losing_lots'])
                account['controlled_exits'] = sum(r['controlled_exits'] for r in subset)
                periods[label][symbol] = account
        save(target, dict(model='observed', variant=variant, rows=rows, ledgers=ledgers, periods=periods))
        print(variant['id'], '56口座完了', flush=True)


def main() -> None:
    """機能: 通信を拒否し、固定又は指定条件の再生を実行する。

    引数: コマンドライン(str)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--ids', default='')
    args = parser.parse_args()
    socket.socket.connect = replay.base_replay.prior.previous.deny
    socket.create_connection = replay.base_replay.prior.previous.deny
    if args.freeze:
        freeze()
        print('二基準と36改修・採否基準を固定しました')
    else:
        run(args.ids.split(',') if args.ids else [])


if __name__ == '__main__':
    main()

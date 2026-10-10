"""事前固定72条件を旧23場と追加2場に分けて再生し、中値と気配を会計する。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle

import numpy as np

from engine import execute, REASONS, CANDIDATE_KEYS
from signals import methods


HERE = Path(__file__).resolve().parent
EXPORT_PATH = HERE.parent / 'wave_v52/export.py'
spec = importlib.util.spec_from_file_location('export59', EXPORT_PATH)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)
DATA_NAMES = ('inputs.pkl', 'quotes.pkl', 'features.pkl', '入口候補.pkl')
CODE_NAMES = ('engine.py', 'backtest.py', 'features.py', 'signals.py', 'check_engine.py')


def clean(value: object) -> object:
    """機能: 非有限数値をnullへ変換して、日本語の公開JSONに格納できる型へ揃える。

    引数: value(object)。返り値: 有限JSON互換の値(object)。
    """
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def save(path: Path, value: object) -> None:
    """機能: 日本語の有限JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def digest(path: Path) -> str:
    """機能: 設定・コード・指定入力の内容を分割読込で固定する。

    引数: path(Path)。返り値: SHA256(str)。明示された段階の入力だけに使用する。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            result.update(block)
    return result.hexdigest()


def stamp() -> str:
    """機能: 凍結・再生の実行時刻を日本時間で記録する。

    引数: なし。返り値: ISO形式の日本時間(str)。
    """
    return datetime.now(timezone(timedelta(hours=9))).isoformat()


def freeze(configs: list[dict], stage: str) -> dict:
    """機能: 旧場損益を見る前に全実行コードと旧入力を固定し、追加場前にも照合する。

    引数: configs(list[dict])、stage(str)。返り値: 固定仕様(dict)。追加場の入力には触れない。
    """
    hashes = {name: digest(HERE / name) for name in CODE_NAMES}
    hashes['../wave_v52/export.py'] = digest(EXPORT_PATH)
    frozen_inputs = {name: digest(HERE / name) for name in DATA_NAMES}
    definition = digest(HERE / '調査仕様.json')
    path = HERE / '実行前固定.json'
    if path.exists():
        frozen = json.loads(path.read_text(encoding='utf8'))
        assert frozen['コードSHA256'] == hashes, '固定後の実行コード変更です'
        assert frozen['旧入力SHA256'] == frozen_inputs, '固定後の旧入力変更です'
        assert frozen['調査仕様SHA256'] == definition and frozen['条件'] == configs
        return frozen
    assert stage == 'dev', '先に旧23場を固定する必要があります'
    frozen = dict(固定時刻=stamp(), 条件=configs, コードSHA256=hashes, 旧入力SHA256=frozen_inputs,
                  調査仕様SHA256=definition, 主条件=[c['id'] for c in configs if c['primary']],
                  価格='次の有効原本行の中値。全注文について同じ行の買ask/売bidを別会計。最後値約定は禁止。',
                  注文='TOPIXmini5枚/NK225micro10枚。追加なし、上限10/20以内。費用0。場末返済・新規最終5分不可・返済後60秒休止。',
                  優先='場末、初期または追跡stop、範囲逸脱、固定利確、10分の順。範囲境界に一致しただけでは逸脱としない。',
                  自動='A1だけ入口regime=1の際に出口X3へ固定。他の入口は設定した出口を用いる。保有後の状態で出口種類を変更しない。',
                  制限='同じ候補列でも出口の違いで保有と休止が変わり、採用入口集合も変化する。出口単独の因果効果とは断定しない。',
                  未読='追加2場の内容を読む前に旧23場を評価し、追加場適用前固定.jsonへ主条件・選定ID・旧結果SHAを固定する。',
                  現在API取得数=0)
    save(path, frozen)
    return frozen


def compact(account: dict) -> dict:
    """機能: 公開用会計から巨大な時価曲線だけを取り除く。

    引数: account(dict)。返り値: 数値・台帳を保持する口座(dict)。
    """
    return {k: ({mode: {field: value for field, value in detail.items() if field not in ('curve', 'w_curve')}
                 for mode, detail in v.items()} if k == 'sensitivity' else v)
            for k, v in account.items() if k not in ('curve', 'w_curve')}


def repriced_legs(account: dict) -> np.ndarray:
    """機能: 同じ全返済組に、注文ごとに保存した売買気配価格を対応付ける。

    引数: account(dict)。返り値: 売買気配の返済16列(ndarray)。
    """
    legs = np.asarray(account['trades'], float).reshape(-1, 16).copy()
    orders = np.asarray(account['orders'], float).reshape(-1, 13)
    prices = np.asarray(account['quote_order_prices'], float)
    legs[:, 4], legs[:, 5] = prices[orders[:, 4] == 1], prices[orders[:, 4] == 2]
    value = 1000. if account['symbol'] == 'TOPIX' else 10.
    legs[:, 6] = legs[:, 2] * legs[:, 3] * (legs[:, 5] - legs[:, 4]) * value
    return legs


def summarize(accounts: list[dict]) -> dict:
    """機能: 同銘柄の利益損失・枚数・保有・出口理由と気配感度をまとめる。

    引数: accounts(list[dict])。返り値: 期間集計(dict)。
    """
    out = export.summarize(accounts)
    legs = np.asarray([t for a in accounts for t in a['trades']], float).reshape(-1, 16)
    groups = np.asarray([g for a in accounts for g in a['width_groups']], float).reshape(-1, 9)
    modes = np.asarray([m for a in accounts for m in a['trade_modes']], int).reshape(-1, 2)
    quote_accounts = [dict(a['sensitivity']['売買気配'], session=a['session']) for a in accounts]
    quote_summary = export.summarize(quote_accounts)
    quote_summary['w_net'] = sum(a['w_net'] for a in quote_accounts)
    out.update(sensitivity={'売買気配': quote_summary},
               candidate_count=sum(a['candidate_count'] for a in accounts),
               candidate_audit={name: sum(a['candidate_audit'][name] for a in accounts) for name in CANDIDATE_KEYS},
               median_hold_minutes=float(np.median(legs[:, 15])) if len(legs) else None,
               mean_hold_minutes=float(legs[:, 15].mean()) if len(legs) else None,
               w_net=float(groups[:, 2].sum()), w_mean=float(groups[:, 2].mean()) if len(groups) else None,
               mean_mfe_width=float(groups[:, 7].mean()) if len(groups) else None,
               effective_exit_counts={f'X{i}': int((modes[:, 0] == i).sum()) for i in (1, 2, 3)},
               regime_counts={'反復': int((modes[:, 1] == 0).sum()), '追従': int((modes[:, 1] == 1).sum())},
               reasons={})
    quote_legs = np.concatenate([repriced_legs(a) for a in accounts], axis=0) if accounts else np.zeros((0, 16))
    for reason in range(1, 7):
        pnl = legs[legs[:, 7] == reason, 6]
        quote_pnl = quote_legs[quote_legs[:, 7] == reason, 6]
        out['reasons'][REASONS[reason]] = dict(cycles=len(pnl), profit=float(pnl[pnl > 0].sum()),
                                             loss=float(-pnl[pnl < 0].sum()), net=float(pnl.sum()),
                                             quote_net=float(quote_pnl.sum()))
    return out


def week(session: str) -> str:
    """機能: セッション開始日を月曜起点の週へまとめる。

    引数: session(str)。返り値: 週の開始日(str)。
    """
    day = datetime.strptime(session[:10], '%Y-%m-%d')
    return (day - timedelta(days=day.weekday())).date().isoformat()


def prepare_stage(stage: str, frozen: dict) -> tuple:
    """機能: 旧場と追加場を分離し、追加場は事前選定と旧結果SHAを確認してから開く。

    引数: stage(str)、frozen(dict)。返り値: 入力ディレクトリ、出力ディレクトリ、段階証跡(tuple)。
    """
    output_dir = HERE / stage
    if stage == 'dev':
        return HERE, output_dir, dict(stage=stage, input_scope='既知の23場', unseen=False)
    assert stage == 'holdout'
    selection_path, dev_result = HERE / '追加場適用前固定.json', HERE / 'dev/売買結果.json'
    selection = json.loads(selection_path.read_text(encoding='utf8'))
    result_hash = digest(dev_result)
    assert result_hash in json.dumps(selection, ensure_ascii=False), '旧結果SHAが選定記録と一致しません'
    assert not (output_dir / '売買結果.json').exists(), '追加場結果は既存です。条件変更や再実行を拒否します'
    assert not (output_dir / '損益再生開始.json').exists(), '追加場の再生は開始済みです'
    evidence = dict(stage=stage, input_scope='事前固定後の追加2場', unseen=True, 開始時刻=stamp(),
                    旧結果SHA256=result_hash, 適用前固定SHA256=digest(selection_path),
                    実行前固定SHA256=digest(HERE / '実行前固定.json'), コードSHA256=frozen['コードSHA256'])
    save(output_dir / '損益再生開始.json', evidence)
    return output_dir, output_dir, evidence


def main() -> None:
    """機能: 明示された段階の72条件だけを再生し、全注文・各場・週・期間会計を保存する。

    引数: CLI --stage dev/holdout、任意 --freeze-only。返り値: なし(None)。
    追加場は親の適用前固定を必須とし、旧場実行では内容を一切開かない。
    """
    parser = argparse.ArgumentParser(description='小幅回収と移動平均の固定72条件再生')
    parser.add_argument('--stage', choices=('dev', 'holdout'), required=True)
    parser.add_argument('--freeze-only', action='store_true')
    args = parser.parse_args()
    configs = methods()
    assert len(configs) == 72 and sum(c['primary'] for c in configs) == 6
    frozen = freeze(configs, args.stage)
    if args.freeze_only:
        print('旧入力とコードの事前固定を確認しました', flush=True)
        return
    data_dir, output_dir, stage_evidence = prepare_stage(args.stage, frozen)
    data_hashes = {name: digest(data_dir / name) for name in DATA_NAMES}
    inputs = pickle.loads((data_dir / 'inputs.pkl').read_bytes())
    quotes = pickle.loads((data_dir / 'quotes.pkl').read_bytes())
    candidates = pickle.loads((data_dir / '入口候補.pkl').read_bytes())
    assert set(inputs) == set(quotes) == set(candidates)
    sessions = sorted({key[0] for key in inputs})
    assert len(sessions) == (23 if args.stage == 'dev' else 2)
    output, audits = [], []
    for ordinal, config in enumerate(configs, 1):
        accounts = []
        for key in sorted(inputs):
            source = candidates[key][config['setting_id']][config['family']]
            source_hash = hashlib.sha256(source.tobytes()).hexdigest()
            qty, value = (5, 1000.) if key[1] == 'TOPIX' else (10, 10.)
            a = execute(inputs[key], quotes[key], source, qty, value, int(config['exit_id'][1:]), config['family'] == 'A1')
            a['intervals'] = export.intervals(inputs[key], a)
            quote_account = dict(a['sensitivity']['売買気配'], trades=repriced_legs(a).tolist())
            a['sensitivity']['売買気配']['intervals'] = export.intervals(inputs[key], quote_account)
            a['source_signal_sha256'] = source_hash
            assert hashlib.sha256(source.tobytes()).hexdigest() == source_hash
            for view in (a, a['sensitivity']['売買気配']):
                assert view['win_qty'] + view['loss_qty'] + view['flat_qty'] == view['cycles'] * qty
                assert abs(view['net'] - (view['profit'] - view['loss'])) < 1e-6
            audits.append(dict(method=config['id'], session=key[0], symbol=key[1],
                               source_sha256=source_hash, candidate_count=len(source),
                               orders=len(a['orders']), cycles=a['cycles'], **a['candidate_audit']))
            accounts.append(a)
        # ----------------------------------------
        # 評価尺度は銘柄別。追加場では旧場との合算・再選抜をしない。
        summary, weeks, periods = {}, {}, {}
        for symbol in ('TOPIX', 'NK225'):
            selected = [a for a in accounts if a['symbol'] == symbol]
            summary[symbol] = summarize(selected)
            weeks[symbol] = {w: summarize([a for a in selected if week(a['session']) == w])
                             for w in sorted({week(s) for s in sessions})}
            sections = ([('前10場', sessions[:10]), ('次9場', sessions[10:19]), ('後4場', sessions[19:])]
                        if args.stage == 'dev' else [('追加2場', sessions)])
            periods[symbol] = {label: summarize([a for a in selected if a['session'] in chosen]) for label, chosen in sections}
        output.append(dict(**config, accounts=[compact(a) for a in accounts], summary=summary, weeks=weeks, periods=periods))
        if config['primary'] or ordinal % 12 == 0:
            print(args.stage, ordinal, config['id'], [(s, summary[s]['net'], summary[s]['sensitivity']['売買気配']['net'],
                                                     summary[s]['cycles']) for s in ('TOPIX', 'NK225')], flush=True)
    # ----------------------------------------
    # 全条件を残し、再生中の入力やコードの変更を拒否する。
    assert all(digest(data_dir / name) == data_hashes[name] for name in DATA_NAMES)
    freeze(configs, args.stage)
    save(output_dir / '売買会計と候補照合.json', dict(合格=True, 段階=args.stage, 口座数=len(audits),
         注文数=sum(a['orders'] for a in audits), 取引組数=sum(a['cycles'] for a in audits), 詳細=audits))
    stage_evidence['実行前固定SHA256'] = digest(HERE / '実行前固定.json')
    save(output_dir / '売買結果.json', dict(methods=output, sessions=sessions, meta=dict(
        **stage_evidence, conditions=72, accounts=72 * len(inputs), main_ids=frozen['主条件'],
        qty='TOPIXmini5枚/NK225micro10枚、追加なし、上限10/20枚', price='次の有効原本行の中値',
        sensitivity='同じ全注文行の買ask/売bid。参照はラージ気配で、実mini/micro約定を保証しない。',
        valuation='中値・気配とも含みは中値で評価。費用0。価格感度であり手数料の試算ではない。',
        current_api_requests=0, 入力SHA256=data_hashes,
        完了時刻=stamp(), interpretation=frozen['制限'])))
    print(f'{args.stage}: 72条件・{len(audits)}口座の会計保存が完了しました', flush=True)


if __name__ == '__main__':
    main()

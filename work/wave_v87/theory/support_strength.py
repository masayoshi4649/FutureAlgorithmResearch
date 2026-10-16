"""保存済みの入口支持強度と完成済み親組を対応させ、閾値探索なしで診断する。"""

import json
import pickle
from datetime import datetime, timezone, timedelta

import numpy as np

from risk_structure import ROOT, HERE, read, sha, quantiles, basic


def local_time(value):
    """
    機能: 保存時計を日本の表示時刻へ変換する。
    引数: value (float) は UNIX 秒。
    返り値: str の年月日・時分秒。
    """
    return datetime.fromtimestamp(float(value), timezone(timedelta(hours=9))).isoformat()


def interval(value):
    """
    機能: 結果を参照せず決めた機構上の境界に支持強度を分類する。
    引数: value (float又はNone) は入口方向へ符号を揃えた30秒中値差/ATR。
    返り値: str の固定区分名。
    """
    if value is None:
        return '欠測'
    if value <= 0:
        return '0以下'
    if value <= .05:
        return '0超0.05以下'
    if value <= .25:
        return '0.05超0.25以下'
    if value <= .75:
        return '0.25超0.75以下'
    return '0.75超'


def event_at(model, ready, row, direction, fixed_atr, peer=False):
    """
    機能: 注文線設定時又は約定直前に公開済みの支持と直前120秒の最後の支持を読む。
    引数: model/ready (dict)、row/direction (int)、fixed_atr (float)、peer (bool)。
    返り値: dict の過去観測だけの特徴。支持状態そのものを再構成したものではない。
    """
    time = float(ready['time_s'][row])
    seq = int(ready['seq'][row])
    index = int(np.searchsorted(model['release'], time, side='left')-1 if peer else
                np.searchsorted(model['seq'], seq, side='right')-1)
    if index < 0:
        return dict(最新=None, 最後の同方向支持=None)

    def record(at):
        """
        機能: 一つの公開特徴を原因診断用の数値に変換する。
        引数: at (int) は公開特徴行。
        返り値: dict の値・公開行・原窓終端・経過時間。
        """
        valid = bool(model['valid'][at])
        ratio = float(direction*model['value'][at]) if valid else None
        movement = ratio*float(model['atr'][at]) if valid else None
        assert int(model['source_seq'][at]) < int(model['seq'][at])
        if peer:
            assert float(model['release'][at]) < time
        else:
            assert int(model['seq'][at]) <= seq
        return dict(有効=valid, 強度ATR=ratio, 方向中値差=movement,
                    固定初期ATR換算=movement/fixed_atr if valid else None,
                    公開時刻=float(model['release'][at]), 公開原本行=int(model['seq'][at])+1,
                    窓終端原本行=int(model['source_seq'][at])+1,
                    公開からの経過秒=time-float(model['release'][at]),
                    特徴計算ATR=float(model['atr'][at]) if valid else None,
                    現閾値の価格幅=.05*float(model['atr'][at]) if valid else None,
                    最新中値=float(model['mid'][at]))

    valid = model['valid'][:index+1]
    support = valid & (direction*model['value'][:index+1] > .05)
    support &= model['release'][:index+1] >= time-120.
    previous = np.flatnonzero(support)
    return dict(最新=record(index), 最後の同方向支持=record(int(previous[-1])) if len(previous) else None)


def strength(row, which='最新'):
    """
    機能: 直前観測の自己支持強度を安全に取り出す。
    引数: row (dict)、which (str) は最新又は最後の同方向支持。
    返り値: float又はNone。
    """
    value = row['約定直前に既知']['自己'][which]
    return value['強度ATR'] if value else None


def group(rows):
    """
    機能: 完成済み親組だけの条件付き集計と過去/事後指標を分けて出す。
    引数: rows (list[dict]) は既存組の明細。
    返り値: dict の会計と診断分布。除外後の戦略損益ではない。
    """
    return dict(既存親組=basic(rows),
                保護目安075到達組=sum(r['価格0.75到達'] for r in rows),
                最終理由が初期停止の組=sum(r['最終理由'] == 1 for r in rows),
                固定初期ATR分布_過去=quantiles([r['固定ATR'] for r in rows]),
                最新中値差呼値分布_過去=quantiles([
                    r['約定直前に既知']['自己']['最新']['方向中値差']/r['呼値'] for r in rows
                    if strength(r) is not None]),
                最大順行ATR分布_事後=quantiles([r['最大順行ATR'] for r in rows]),
                最大逆行ATR分布_事後=quantiles([r['最大逆行ATR'] for r in rows]),
                元注文線から約定飛び呼値_事後=quantiles([r['約定飛び呼値'] for r in rows]),
                直前価格の追跡極値からの反発ATR_過去=quantiles([r['直前価格の極値からの反発ATR'] for r in rows]),
                直前最新支持ATR_過去=quantiles([strength(r) for r in rows if strength(r) is not None]),
                最後の同方向支持ATR_過去=quantiles([strength(r, '最後の同方向支持') for r in rows
                                                   if strength(r, '最後の同方向支持') is not None]))


def main():
    """
    機能: 原GUと狭い追尾再参加の旧台帳を公開済み支持へ対応させる。
    引数: なし。
    返り値: None。支持診断と明細を保存し、新戦略の売買は実行しない。
    """
    fixed = dict(対象=['E01_G_U', 'T2_P1'], 売買再生なし=True,
                 境界=['0以下', '0超0.05以下', '0.05超0.25以下', '0.25超0.75以下', '0.75超', '欠測'],
                 境界根拠='0は方向不支持、.05は元支持条件、.25は新規反発幅、.75は狭幅保護始動の目安。結果に合わせた閾値選択はしない。',
                 参照時点=['注文線を設定した原本行', '約定原本行の一行前'],
                 期間=['全30', '前16', '後14'],
                 注意='既存親組の条件付き集計。見送ると時計と後続新規が変わるため、見送り改修の収支ではない。')
    (HERE/'支持強度診断の固定条件.json').write_text(json.dumps(fixed, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    proof_path = ROOT/'work/wave_v85/prepared/入力準備の完了.json'
    proof = read(proof_path)
    fingerprints = {str(proof_path.relative_to(ROOT)): sha(proof_path)}
    inputs = {}
    for pair in proof['入力対応']:
        path = ROOT/pair['inputs']
        assert sha(path) == proof['使用入力SHA256'][pair['inputs']]
        fingerprints[pair['inputs']] = sha(path)
        with path.open('rb') as stream:
            inputs.update(pickle.load(stream))
    short_path = ROOT/'work/wave_v87/round3/prepared/short.pkl'
    short_proof = read(short_path.with_name('支持準備の照合.json'))
    assert short_proof['出力SHA256'] == sha(short_path)
    fingerprints[str(short_path.relative_to(ROOT))] = sha(short_path)
    with short_path.open('rb') as stream:
        models = pickle.load(stream)['events']
    existing_path = HERE/'既存親組の価格経路明細.json'
    existing = read(existing_path)
    fingerprints[str(existing_path.relative_to(ROOT))] = sha(existing_path)
    sessions = sorted({key[0] for key in inputs})
    details = []
    expected = {}
    prefix_checks = 0
    for method, relative in [('E01_G_U', 'work/wave_v86/observed/ledgers/E01_G_U.pkl'),
                             ('T2_P1', 'work/wave_v86/phase2/observed/ledgers/T2_P1.pkl')]:
        path = ROOT/relative
        result_path = path.parent.parent/'results'/f'{method}.json'
        original = read(result_path)
        expected[method] = original['periods']
        fingerprints[str(result_path.relative_to(ROOT))] = sha(result_path)
        assert sha(path) == original['ledger_SHA256']
        fingerprints[relative] = sha(path)
        with path.open('rb') as stream:
            ledgers = pickle.load(stream)
        old_rows = {(r['セッション'], r['銘柄'], r['組']): r for r in existing[method]}
        for key, account in sorted(ledgers.items()):
            ready = inputs[key]
            peer_key = (key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX')
            preparations = {int(r[0]): int(r[3]) for r in account['entry_preparations']}
            for order in account['orders']:
                if order[7] != 1:
                    continue
                entry, source, cid, side = map(int, order[:4])
                row = dict(old_rows[(key[0], key[1], cid)])
                atr, tick = float(row['固定ATR']), float(ready['tick'])
                prep = preparations[cid]
                assert prep <= source < entry
                before = np.asarray(ready['last'][prep:entry], float)
                valid = np.isfinite(before) & (before > 0)
                extreme = float(before[valid].min() if side > 0 else before[valid].max())
                last_known = float(before[valid][-1])
                trigger = extreme+side*.25*atr
                trigger = (np.ceil(trigger/tick-1e-9) if side > 0 else np.floor(trigger/tick+1e-9))*tick
                row.update(新規時刻=local_time(ready['time_s'][entry]), 新規原本行=int(ready['seq'][entry])+1,
                           注文元行=source, 注文元原本行=int(ready['seq'][source])+1,
                           直前原本行=int(ready['seq'][entry-1])+1, 準備行=prep,
                           直前価格の極値からの反発ATR=side*(last_known-extreme)/atr,
                           注文線=float(trigger), 約定飛び呼値=float(side*(row['建値']-trigger)/tick),
                           呼値=tick, 片道料相当価格=.0418 if key[1] == 'TOPIX' else 1.1,
                           固定ATRでのT2保護始動目安=.75*atr,
                           注文線設定から約定まで秒=float(ready['time_s'][entry]-ready['time_s'][source]))
                for label, index in [('注文線設定時に既知', source), ('約定直前に既知', entry-1)]:
                    row[label] = dict(自己=event_at(models[key], ready, index, side, atr),
                                      相手=event_at(models[peer_key], ready, index, side, atr, peer=True))
                # ----------------------------------------
                # 各口座の先頭新規では、判定後の公開特徴を切り落としても診断が変わらないことを確認する。
                if cid == int(account['cycles'][0][0]):
                    for peer, model_key, name in [(False, key, '自己'), (True, peer_key, '相手')]:
                        model = models[model_key]
                        stop = int(np.searchsorted(model['release'], ready['time_s'][entry-1], side='left') if peer else
                                   np.searchsorted(model['seq'], ready['seq'][entry-1], side='right'))
                        cut = {field: values[:stop] for field, values in model.items()}
                        assert event_at(cut, ready, entry-1, side, atr, peer) == row['約定直前に既知'][name]
                        prefix_checks += 1
                row['最新支持区分'] = interval(strength(row))
                row['最後の同方向支持区分'] = interval(strength(row, '最後の同方向支持'))
                details.append(row)

    # ----------------------------------------
    # 境界や手法を選び直さず、全体と同じ既存の前後期間で表を作る。
    summary = []
    for method in fixed['対象']:
        for symbol in ('TOPIX', 'NK225'):
            for period, allowed in [('全30', sessions), ('前16', sessions[:16]), ('後14', sessions[16:])]:
                rows = [r for r in details if r['手法'] == method and r['銘柄'] == symbol and r['セッション'] in allowed]
                target = expected[method][period][symbol]
                account = basic(rows)
                assert abs(account['収支']-target['net']) < 1e-7
                assert abs(account['手数料']-target['fees']) < 1e-7
                assert account['組数'] == target['campaigns']
                bins = {which: {band: group([r for r in rows if r[which] == band]) for band in fixed['境界']}
                        for which in ('最新支持区分', '最後の同方向支持区分')}
                supported = [r for r in rows if strength(r) is not None and strength(r) > .05]
                latest = [r['約定直前に既知']['自己']['最新'] for r in rows]
                latest = [r for r in latest if r and r['有効']]
                summary.append(dict(手法=method, 銘柄=symbol, 期間=period, 全組=group(rows), 固定区分=bins,
                                    最新自己支持あり=group(supported),
                                    最新自己支持なし=group([r for r in rows if r not in supported]),
                                    現閾値が半呼値未満の組=sum(r['現閾値の価格幅'] < (.25 if symbol == 'TOPIX' else 5.) for r in latest),
                                    現閾値が1呼値未満の組=sum(r['現閾値の価格幅'] < (.5 if symbol == 'TOPIX' else 10.) for r in latest),
                                    最新支持の公開経過秒=quantiles([r['公開からの経過秒'] for r in latest]),
                                    閾値の呼値換算=quantiles([r['現閾値の価格幅']/(.5 if symbol == 'TOPIX' else 10.) for r in latest])))

    evidence = []
    for method in fixed['対象']:
        for symbol in ('TOPIX', 'NK225'):
            rows = [r for r in details if r['手法'] == method and r['銘柄'] == symbol]
            groups = [('強い最新支持でも初期停止', [r for r in rows if strength(r) is not None and strength(r) > .75 and r['最終理由'] == 1]),
                      ('弱い最新支持でも勝つ', [r for r in rows if strength(r) is not None and 0 < strength(r) <= .25 and r['収支'] > 0]),
                      ('最新支持消失後でも勝つ', [r for r in rows if strength(r) is not None and strength(r) <= .05 and r['収支'] > 0])]
            for name, local in groups:
                evidence.append(dict(手法=method, 銘柄=symbol, 反例=name, 総組数=len(local),
                                     抽出規則='該当する既存親組の時系列先頭2件。金額最大や都合のよい場を選ばない。', 明細=local[:2]))
    assert len(details) == 1096
    output = dict(新売買再生なし=True, 新閾値選抜なし=True, 全入口1096照合=True,
                  未来の公開特徴切断比較数=prefix_checks, 既存期間会計12口座集計一致=True,
                  固定条件=fixed, 入力SHA256=fingerprints, 集計=summary, 反例=evidence,
                  解釈制約=[
                      '.05ATRは過去30秒のタイミング条件であり、将来.75ATR進む予測値ではない。比だけでは原因にならない。',
                      '.75到達はT2の保護始動目安を価格差で見た事後診断で、GUの元始動条件とは異なる。呼値丸め後の実エンジン発動とも区別する。',
                      '最新支持と最後の同方向支持を区別。後者は直前120秒内の最後の公開イベントで、主方向変化を含む元保持状態の完全再構成ではない。',
                      '約定の一行前までの特徴だけを過去観測とする。約定値、最大順行、最大逆行、最終収支は事後診断。',
                      'この金額は旧台帳の部分集合。除外に伴う影時計・新規機会の変化を再生しておらず、改修後の利益とは呼ばない。',
                      '強い直近変化は推進力だけでなく追い掛け・既に進んだ距離も含む。条件付き関連から因果を断定しない。',
                      'CurrentPriceTimeは代理時計で、同時計別行の実際の受信順時刻は検証できない。',
                      '料金相当価格は通常片道41.8円/1000円と11円/10円。往復・気配差・観測飛びは別途必要。'])
    (HERE/'入口支持強度と既存親組の診断.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    (HERE/'入口支持強度の親組明細.json').write_text(json.dumps(details, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    for item in summary:
        if item['期間'] == '全30':
            print(json.dumps(dict(手法=item['手法'], 銘柄=item['銘柄'], 組数=item['全組']['既存親組']['組数'],
                                  強度別=[dict(区分=band, **item['固定区分']['最新支持区分'][band]['既存親組']) for band in fixed['境界']],
                                  閾値半呼値未満=item['現閾値が半呼値未満の組']), ensure_ascii=False))


if __name__ == '__main__':
    main()

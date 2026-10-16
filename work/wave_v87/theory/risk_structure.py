"""既存台帳と保有中の保存価格から初期損失枠と順行前逆行を診断する。"""

import hashlib
import json
import pickle
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'work/wave_v86'


def read(path):
    """
    機能: 保存済み日本語JSONを読む。
    引数: path (Path) は対象ファイル。
    返り値: dict又はlist の復元資料。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: 読取元ファイルのSHA256を求める。
    引数: path (Path) は対象ファイル。
    返り値: str の指紋。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def quantiles(values):
    """
    機能: 診断量の分位点を固定した割合でまとめる。
    引数: values (list[float]) は対象数値。
    返り値: dict又はNone の10・25・50・75・90%分位点。
    """
    if not values:
        return None
    return dict(zip(('p10', 'p25', 'p50', 'p75', 'p90'),
                    map(float, np.quantile(values, (.1, .25, .5, .75, .9)))))


def basic(rows):
    """
    機能: 親組単位の金額と勝ち負けの構造を集計する。
    引数: rows (list[dict]) は完成済み親組の診断明細。
    返り値: dict の会計・損益分布。
    """
    gains = [r['収支'] for r in rows if r['収支'] > 0]
    losses = [-r['収支'] for r in rows if r['収支'] < 0]
    gain, loss = sum(gains), sum(losses)
    aw, al = gain / len(gains) if gains else None, loss / len(losses) if losses else None
    return dict(組数=len(rows), 勝組=len(gains), 負組=len(losses),
                利益=gain, 損失=loss, 収支=gain-loss,
                手数料=sum(r['手数料'] for r in rows), 粗損益=sum(r['粗損益'] for r in rows),
                平均勝ち=aw, 平均負け=al,
                平均勝負比=aw/al if aw is not None and al else None,
                勝率=len(gains)/len(rows) if rows else None,
                観測平均勝負額での損益分岐勝率=al/(aw+al) if aw is not None and al else None,
                金額利益割合=gain/(gain+loss) if gain+loss else None,
                粗黒字だが料金後負け=sum(r['粗損益'] > 0 and r['収支'] < 0 for r in rows),
                収支分布=quantiles([r['収支'] for r in rows]),
                損益R分布=quantiles([r['損益R'] for r in rows]),
                初期名目損失枠分布=quantiles([r['初期名目損失枠円'] for r in rows]),
                料金対R比分布=quantiles([r['手数料']/r['R円'] for r in rows]))


def summarize(rows):
    """
    機能: 既存価格経路の順序から短縮ストップの反証に必要な数値をまとめる。
    引数: rows (list[dict]) は同一手法・商品・期間の親組明細。
    返り値: dict の事後診断。反実仮想の損益再生ではない。
    """
    hit = [r for r in rows if r['価格0.75到達']]
    never = [r for r in rows if not r['価格0.75到達']]
    cut = {}
    for level in ('.25', '.5'):
        affected = [r for r in rows if r['先に逆行'+level]]
        winners = [r for r in affected if r['収支'] > 0]
        cut[level] = dict(先に逆行した既存組=basic(affected),
                          うち既存勝組=basic(winners),
                          うち後で0_75順行=basic([r for r in affected if r['価格0.75到達']]),
                          注記='既存の保有経路に当該逆行が先にあったという診断。新しいストップによる損益・新規経路は未計算。')
    bins = {}
    for low, high in ((0, .25), (.25, .5), (.5, .75), (.75, 1.5), (1.5, 1e99)):
        local = [r for r in rows if low <= r['最大順行ATR'] < high]
        bins[f'{low}以上{high if high < 1e90 else "無限"}未満'] = basic(local)
    return dict(全組=basic(rows), 価格0_75到達組=basic(hit), 未到達組=basic(never),
                到達前最大逆行ATR分布=quantiles([r['到達まで最大逆行ATR'] for r in hit]),
                勝組の到達前最大逆行ATR分布=quantiles([r['到達まで最大逆行ATR'] for r in hit if r['収支'] > 0]),
                先行逆行反証=cut, 最大順行帯=bins,
                返済理由={str(reason): basic([r for r in rows if r['最終理由'] == reason])
                            for reason in sorted({r['最終理由'] for r in rows})})


def extract(ledgers, inputs, method):
    """
    機能: 初回から全返済までの実台帳を価格経路と対応させる。
    引数: ledgers/inputs (dict)、method (str) は保存手法ID。
    返り値: list[dict] の組別診断明細。
    """
    rows = []
    for key, ledger in sorted(ledgers.items()):
        ready = inputs[key]
        previous = None
        for cycle in ledger['cycles']:
            cid, start, end = map(int, cycle[:3])
            atr, direction = float(cycle[5]), int(cycle[8])
            legs = [r for r in ledger['net_trades'] if r['組'] == cid]
            entries = [o for o in ledger['orders'] if int(o[2]) == cid and o[7] == 1]
            assert len(entries) == 1 and int(entries[0][0]) == start
            qty, entry = int(entries[0][4]), float(entries[0][5])
            unit = 1000 if key[1] == 'TOPIX' else 10
            risk = qty * atr * unit
            # ----------------------------------------
            # 新規と同じ行は含めず、保存された保有中観測だけを事後診断に使用する。
            raw = np.asarray(ready['last'][start+1:end+1], float)
            raw_indices = np.arange(start+1, end+1)
            valid = np.isfinite(raw) & (raw > 0)
            raw, indices = raw[valid], raw_indices[valid]
            progress = direction * (raw-entry) / atr
            hits = np.flatnonzero(progress >= .75)
            first = int(hits[0]) if len(hits) else None
            before = progress[:first+1] if first is not None else progress
            row = dict(手法=method, セッション=key[0], 銘柄=key[1], 組=cid,
                       新規行=start, 返済行=end, 方向=direction, 初回枚数=qty, 建値=entry,
                       固定ATR=atr, R円=risk, 初期名目損失枠円=.75*risk,
                       粗損益=float(sum(r['利益損失前'] for r in legs)),
                       手数料=float(sum(r['手数料'] for r in legs)),
                       収支=float(sum(r['収支'] for r in legs)),
                       価格0_75到達行=int(indices[first]) if first is not None else None,
                       最大順行ATR=max(0.,float(progress.max())) if len(progress) else 0.,
                       最大逆行ATR=max(0.,float(-progress.min())) if len(progress) else 0.,
                       到達まで最大逆行ATR=max(0.,float(-before.min())) if len(before) else 0.,
                       最終理由=int(cycle[9]),
                       前組黒字=previous is not None and previous['収支'] > 0,
                       前組同方向=previous is not None and previous['方向'] == direction)
            row['価格0.75到達'] = first is not None
            row['損益R'] = row['収支'] / risk
            if int(cycle[9]) == 1 and len(legs) == 1 and int(legs[0]['枚数']) == qty:
                tick = float(ready['tick'])
                raw_stop = entry-direction*.75*atr
                stop = (np.floor(raw_stop/tick+1e-9) if direction > 0 else
                        np.ceil(raw_stop/tick-1e-9))*tick
                rounding = (direction*(entry-stop)-.75*atr)*qty*unit
                jump = direction*(stop-float(legs[0]['返済値']))*qty*unit
                assert jump >= -1e-6, (key, cid, '名目丸め線より手前の損切り', jump)
                assert abs(.75*risk+rounding+jump+row['手数料']+row['収支']) < 1e-5
                row['初期損切り分解'] = dict(名目損失=.75*risk, 呼値丸め追加=float(rounding),
                                             観測飛び追加=float(jump), 料金=row['手数料'])
            for label, level in (('.25', .25), ('.5', .5)):
                adverse = np.flatnonzero(progress <= -level)
                row['先に逆行'+label] = bool(len(adverse) and (first is None or adverse[0] < first))
            assert abs(row['粗損益'] - row['手数料'] - row['収支']) < 1e-6
            assert abs(cycle[3]*unit - row['粗損益']) < 1e-6
            rows.append(row)
            previous = row
    return rows


def main():
    """
    機能: 原広幅・狭幅のみ・狭幅利確後再参加の三経路を読むだけで診断する。
    引数: なし。
    返り値: None。理論資料と明細JSONを保存する。新戦略の売買再生は行わない。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    proof_path = ROOT / 'work/wave_v85/prepared/入力準備の完了.json'
    proof = read(proof_path)
    inputs, fingerprints = {}, {str(proof_path.relative_to(ROOT)): sha(proof_path)}
    for pair in proof['入力対応']:
        path = ROOT / pair['inputs']
        actual = sha(path)
        assert actual == proof['使用入力SHA256'][pair['inputs']]
        fingerprints[pair['inputs']] = actual
        with path.open('rb') as stream:
            inputs.update(pickle.load(stream))
    fixed = read(OLD / 'phase2/事前固定.json')
    allrows, methods = [], {}
    for method, folder in [('E01_G_U', OLD), ('T2_S', OLD), ('T2_P1', OLD / 'phase2')]:
        resultpath = folder / 'observed/results' / (method + '.json')
        ledgerpath = folder / 'observed/ledgers' / (method + '.pkl')
        result = read(resultpath)
        assert sha(ledgerpath) == result['ledger_SHA256']
        fingerprints[str(resultpath.relative_to(ROOT))] = sha(resultpath)
        fingerprints[str(ledgerpath.relative_to(ROOT))] = result['ledger_SHA256']
        with ledgerpath.open('rb') as stream:
            ledgers = pickle.load(stream)
        rows = extract(ledgers, inputs, method)
        methods[method] = rows
        for period in ('前16', '後14', '全30'):
            for symbol in ('TOPIX', 'NK225'):
                selected = [r for r in rows if r['銘柄'] == symbol and r['セッション'] in fixed[period]]
                total = sum(r['収支'] for r in selected)
                assert abs(total-result['periods'][period][symbol]['net']) < 1e-6
                allrows.append(dict(手法=method, 期間=period, 銘柄=symbol, **summarize(selected)))
        print(method, len(rows), '組の会計と保有経路を照合', flush=True)
    extra = []
    for symbol in ('TOPIX', 'NK225'):
        keys = {(r['セッション'], r['新規行'], r['方向']) for r in methods['T2_S'] if r['銘柄'] == symbol}
        rows = [r for r in methods['T2_P1'] if r['銘柄'] == symbol]
        added = [r for r in rows if (r['セッション'], r['新規行'], r['方向']) not in keys]
        extra.append(dict(銘柄=symbol, 比較='T2_Sに同一新規行・方向がないT2_P1の組',
                          追加組=summarize(added),
                          うち前組黒字同方向=summarize([r for r in added if r['前組黒字'] and r['前組同方向']])))
    overshoot = []
    for method, rows in methods.items():
        for symbol in ('TOPIX', 'NK225'):
            selected = [r for r in rows if r['銘柄'] == symbol and '初期損切り分解' in r]
            sums = {key: sum(r['初期損切り分解'][key] for r in selected)
                    for key in ('名目損失', '呼値丸め追加', '観測飛び追加', '料金')}
            total_loss = -sum(r['収支'] for r in selected)
            assert abs(sum(sums.values())-total_loss) < 1e-5
            overshoot.append(dict(手法=method, 銘柄=symbol, 全量一括初期損切り組=len(selected),
                                  損失=total_loss, 分解=sums,
                                  観測飛びあり組=sum(r['初期損切り分解']['観測飛び追加'] > 1e-7 for r in selected)))
    value = dict(新戦略損益再生=False, 指定価格モデル再計算=False,
                 目的='初期損失と狭幅追跡の非対称、ノイズ逆行で消える既存勝ちの量を事後診断する。',
                 観測現在値のみ=True, 全期間会計一致=True, 商品別期間=allrows,
                 追加経路の構造=extra, 初期全量損切りの超過分解=overshoot, 読取資料SHA256=fingerprints,
                 制約=['保存された初回から全返済までのみを解析。返済後の未来価格を勝ち判定に足していない。',
                       '最大順行・逆行は事後診断のみ。実行アルゴリズムの入口・出口には使わない。',
                       '0.75ATR到達は実際の建値を起点とする価格障壁診断であり、丸め・前行計画を含むエンジンの追跡発動証跡そのものではない。',
                       '既存勝組で先に0.25/0.5ATR逆行した件数は短縮ストップの犠牲候補。新損益や新しい入口回数を表さない。',
                       '共通入口以外の組は経路追加の説明であり、完全な因果分解ではない。',
                       '全30場は既知。商品間の円額は合算しない。真の受信時刻・小型商品の気配約定は未復元。'])
    (HERE / '初期リスクと順行前逆行の診断.json').write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    (HERE / '既存親組の価格経路明細.json').write_text(
        json.dumps(methods, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    for row in allrows:
        if row['期間'] == '全30':
            account = row['全組']
            print(json.dumps(dict(手法=row['手法'], 銘柄=row['銘柄'], 組数=account['組数'],
                                  収支=account['収支'], 平均勝負比=account['平均勝負比'],
                                  未到達組損失割合=row['未到達組']['損失']/account['損失']), ensure_ascii=False))


if __name__ == '__main__':
    main()

"""J2のTOPIX赤字上位三場を既存台帳と生板へ戻して説明し、売買は再生しない。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import pickle
import socket

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JST = timezone(timedelta(hours=9))
SESSIONS = ('2026-10-05_Day', '2026-09-25_Night', '2026-09-22_Night')
METHOD = 'J2_F0_B0_H0_R0'
REASONS = {1: '初期損切り', 2: '幅トレーリング', 3: '30分期限', 4: '場内返済'}


def load(name: str) -> object:
    """機能: 既存の保存素材を読取専用で開く。

    引数: name(str) はルート相対名。返り値: 保存内容(object)。
    """
    path = ROOT / name
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def clean(value: object) -> object:
    """機能: numpy値と未定義値をJSONへ安全に直す。

    引数: value(object)。返り値: JSONで記述可能な値(object)。
    """
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def save(name: str, value: object) -> None:
    """機能: 担当する新しい診断領域だけへ出力する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def clock(stamp: float) -> str:
    """機能: 最終約定の代理時計を日本時刻として表示する。

    引数: stamp(float)。返り値: ISO日時(str)。受信時刻とは区別する。
    """
    return datetime.fromtimestamp(float(stamp), JST).isoformat()


def deny(*args: object, **kwargs: object) -> None:
    """機能: 生板診断で外部接続を禁止する。

    引数: 任意(tuple/dict)。返り値: なし(None)、常に例外。
    """
    raise RuntimeError('保存済み資料だけを診断する')


def point(r: dict, f: dict, i: int) -> dict:
    """機能: 抽出行を原本行番号と気配へ対応付ける。

    引数: r/f(dict)、i(int)。返り値: 日本時刻・原本行・価格数量(dict)。
    """
    return dict(抽出行=i, 原本0始まり行=int(r['seq'][i]), 原本1始まり行=int(r['seq'][i])+1,
                最終約定時計=clock(r['time_s'][i]), **{k: f[k][i] for k in ('last', 'bid', 'ask', 'bid_qty', 'ask_qty', 'best_ofi', 'volume_delta')})


def asof(r: dict, f: dict, deadline: float) -> int:
    """機能: 旧入口と同じstrict asofで同時計先頭の過去観測だけを選ぶ。

    引数: r/f(dict)、deadline(float)。返り値: 抽出行(int)。品質不良は救済しない。
    """
    times = r['time_s']
    end = int(np.searchsorted(times, deadline, side='left'))-1
    assert end >= 0
    i = int(np.searchsorted(times, times[end], side='left'))
    assert 0 < deadline-times[i] <= 30 and f['valid'][i] and not f['reset'][i]
    assert 0 < f['ask'][i]-f['bid'][i] <= 2*r['tick']+1e-9
    return i


def source_state(r: dict, f: dict, grid_time: float, expected_now: int) -> dict:
    """機能: 実際の旧入口の300秒・15秒根拠を保存原本行から復元する。

    引数: r/f(dict)、grid_time(float)、expected_now(int)。返り値: 当時の根拠(dict)。
    """
    now = asof(r, f, grid_time-5.)
    old = asof(r, f, grid_time-305.)
    short = asof(r, f, grid_time-20.)
    assert now == expected_now
    sample = f['best_ofi'][short+1:now+1]
    assert np.isfinite(sample).all()
    absolute = float(np.abs(sample).sum())
    return dict(現在=point(r, f, now), 過去300秒=point(r, f, old), 過去15秒=point(r, f, short),
                実時間300秒=float(r['time_s'][now]-r['time_s'][old]), 実時間15秒=float(r['time_s'][now]-r['time_s'][short]),
                進行300bp=float((f['mid'][now]/f['mid'][old]-1)*10000),
                進行15bp=float((f['mid'][now]/f['mid'][short]-1)*10000),
                bid進行15呼値=float((f['bid'][now]-f['bid'][short])/r['tick']),
                ask進行15呼値=float((f['ask'][now]-f['ask'][short])/r['tick']),
                OFI15比=float(sample.sum()/absolute) if absolute else 0.,
                OFI15和=float(sample.sum()), OFI15絶対和=absolute, 非ゼロOFI数=int(np.count_nonzero(sample)))


def filter_state(market: dict, g: int, direction: int) -> dict:
    """機能: 旧候補の採否に実際に使ったJ2の追加フィルターを抜き出す。

    引数: market(dict)、g/direction(int)。返り値: 同時点の観測品質と値(dict)。
    """
    f = market['flow'][15]
    enough = bool(f['source_valid'][g] and f['valid'][g] and not f['missing_ofi'][g]
                  and f['nonzero_ofi_count'][g] >= 3 and np.isfinite(f['ofi_ratio'][g]))
    return dict(現在={k: v[g] for k, v in market['current'].items()},
                進行300秒={k: v[g] for k, v in market['windows'][300].items()},
                フロー15秒={k: v[g] for k, v in f.items()}, フロー観測十分=enough,
                明確な逆OFI=enough and direction*f['ofi_ratio'][g] <= -.1,
                同方向OFI支持=enough and direction*f['ofi_ratio'][g] >= .1,
                レンジ180秒={k: v[g] for k, v in market['ranges'][180].items()})


def after_marks(r: dict, f: dict, grid: dict, state: dict, trade: np.ndarray) -> dict:
    """機能: 判断後の実際の保有区間だけで順行・逆行と既知状態の変化を測る。

    引数: r/f/grid/state(dict)、trade(ndarray)。返り値: 事後診断(dict)。新売買は作らない。
    """
    _, ent, ext, side, qty, price, _, ef, xf = trade[:9]
    ei, xi, side = int(ent), int(ext), int(side)
    quote = f['bid'] if side == 1 else f['ask']
    move = side*(quote[ei:xi+1]-price)
    peak, worst = ei+int(np.argmax(move)), ei+int(np.argmin(move))
    nets = move*qty*1000-ef-xf
    crosses = np.flatnonzero((move[:-1] > (ef+xf)/(qty*1000)) & (move[1:] <= (ef+xf)/(qty*1000)))+ei+1
    future = (state['grid'] >= r['time_s'][ei]) & (state['grid'] <= r['time_s'][xi])
    opposite_flow = np.ones(len(state['grid']), bool)
    same_flow = opposite_flow.copy()
    opposite_price15 = opposite_flow.copy()
    for symbol in ('TOPIX', 'NK225'):
        fl = grid['markets'][symbol]['flow'][15]
        enough = fl['source_valid'] & fl['valid'] & ~fl['missing_ofi'] & (fl['nonzero_ofi_count'] >= 3) & np.isfinite(fl['ofi_ratio'])
        opposite_flow &= enough & (side*fl['ofi_ratio'] <= -.1)
        same_flow &= enough & (side*fl['ofi_ratio'] >= .1)
        opposite_price15 &= fl['source_valid'] & (side*fl['bid_change_ticks'] <= -1.+1e-8) & (side*fl['ask_change_ticks'] <= -1.+1e-8)
    definitions = {
        '初めて共通方向が消失': state['valid'] & (state['common'] != side),
        '初めて両300秒方向が反転': state['current300_valid'] & (state['trend300'] == -side),
        '初めて共通300秒30秒方向が反転': state['valid'] & (state['common'] == -side),
        '初めて双方15秒OFIが逆': opposite_flow,
        '初めて双方15秒両気配が逆': opposite_price15,
        '初めてFD反対15秒持続': state['fd_long'] if side == 1 else state['fd_short'],
        '初めてFDと価格反対15秒持続': state['fd_price_long'] if side == 1 else state['fd_price_short'],
    }
    flags = {}
    for name, flag in definitions.items():
        indexes = np.flatnonzero(future & flag)
        if not len(indexes):
            flags[name] = None
            continue
        g = int(indexes[0]); when = state['grid'][g]
        own = int(np.searchsorted(r['time_s'], when, side='left'))
        flags[name] = dict(判断予定時計=clock(when), 新規から秒=float(when-r['time_s'][ei]),
                           最初の自市場行=point(r, f, own),
                           同行清算評価円=float(side*(quote[own]-price)*qty*1000-ef-xf),
                           注意='同行価格で約定したという意味ではなく、保存された建玉の時価評価。予防戦略の損益ではない。')
    return dict(最大順行pt=float(move.max()), 最大順行清算評価円=float(nets.max()), 最大順行時点=point(r, f, peak),
                最大逆行pt=float(move.min()), 最大逆行清算評価円=float(nets.min()), 最大逆行時点=point(r, f, worst),
                順行頂点から最終返済までの減少円=float(nets.max()-trade[10]),
                初めて費用後黒字から赤字へ戻った時刻=clock(r['time_s'][int(crosses[0])]) if len(crosses) else None,
                後に観測された状態=flags, 保有中の両同方向OFI支持格子数=int((future & same_flow).sum()))


def raw_snapshot(seq: int, raw: dict) -> dict:
    """機能: 原本の板十段・累積出来高と時計をそのまま小窓に保存する。

    引数: seq(int)、raw(dict)。返り値: 原本行を付けた必要項目(dict)。
    """
    names = ['CurrentPriceTime', 'CurrentPrice', 'TradingVolume', 'TradingValue']
    names += [f'{side}{i}' for side in ('Buy', 'Sell') for i in range(1, 11)]
    return dict(原本0始まり行=seq, 原本1始まり行=seq+1, **{name: raw.get(name) for name in names})


def raw_window(rows: list[dict]) -> dict:
    """機能: 価格を固定した表示増減を集計し、補充候補と約定・取消の限界を分ける。

    引数: rows(list[dict]) は判断前の連続原本小窓。返り値: 集計(dict)。
    """
    changes = {}; compact = []; zero_volume_recoveries = 0
    for i, now in enumerate(rows):
        compact.append([now['原本1始まり行'], now['CurrentPriceTime'], now['CurrentPrice'], now['TradingVolume'],
                        *(now.get(side+'1', {}).get(field) for side in ('Buy', 'Sell') for field in ('Price', 'Qty'))])
        if i == 0:
            continue
        before = rows[i-1]
        for side in ('Buy', 'Sell'):
            old = {before[side+str(j)]['Price']: before[side+str(j)]['Qty'] for j in range(1, 11)}
            new = {now[side+str(j)]['Price']: now[side+str(j)]['Qty'] for j in range(1, 11)}
            for price in old.keys()-new.keys():
                if (side, price) in changes:
                    changes[(side, price)]['最後の減少残量'] = 0
            for price in old.keys() & new.keys():
                diff = new[price]-old[price]
                if diff == 0:
                    continue
                item = changes.setdefault((side, price), dict(側=side, 価格=price, 表示追加枚数=0, 表示減少枚数=0,
                                          減少後の回復観測枚数=0, 最後の減少残量=0, 変化回数=0, 回復例=[]))
                item['変化回数'] += 1
                if diff < 0:
                    item['表示減少枚数'] -= diff; item['最後の減少残量'] -= diff
                else:
                    item['表示追加枚数'] += diff
                    recovery = min(diff, item['最後の減少残量'])
                    item['減少後の回復観測枚数'] += recovery; item['最後の減少残量'] -= recovery
                    if recovery and len(item['回復例']) < 2:
                        item['回復例'].append(dict(時刻=now['CurrentPriceTime'], 原本行=now['原本1始まり行'],
                                                  前量=old[price], 後量=new[price], 回復量=recovery,
                                                  累積出来高差=now['TradingVolume']-before['TradingVolume']))
                    if recovery and now['TradingVolume'] == before['TradingVolume']:
                        zero_volume_recoveries += 1
    ranked = sorted(changes.values(), key=lambda x: (-x['減少後の回復観測枚数'], -x['変化回数'], x['価格']))
    return dict(始点=rows[0]['原本1始まり行'], 終点=rows[-1]['原本1始まり行'], 原本行数=len(rows),
                実観測開始時計=rows[0]['CurrentPriceTime'], 実観測終了時計=rows[-1]['CurrentPriceTime'],
                実観測秒=(datetime.fromisoformat(rows[-1]['CurrentPriceTime'])-datetime.fromisoformat(rows[0]['CurrentPriceTime'])).total_seconds(),
                窓名の意味='15秒は参照期限の間隔。最終約定時計の停止と30秒の最大許容古さにより、実観測秒は15秒と異なる。',
                同一価格の表示変化=ranked, 出来高不変の回復観測回数=zero_volume_recoveries,
                判別限界='共通表示価格だけの増減。減少は約定と取消を分離できず、増加は新規指値・再提示を分離できない。板の十段外への移動は取消に数えない。価格別約定系列がないためアイスバーグ又は機関の補充とは断定しない。',
                小窓列=['原本行', '最終約定時計', '現在値', '累積出来高', 'bid', 'bid数量', 'ask', 'ask数量'], 小窓=compact)


def extract_raw(requests: dict, ready: dict, features: dict) -> dict:
    """機能: 必要な行だけ原本を復号し、両市場の判断前小窓と生の板を対応付ける。

    引数: requests/ready/features(dict)。返り値: 原本抜粋への参照と指紋(dict)。
    """
    output = {}
    for key, request in requests.items():
        session, symbol = key
        wanted = set(request['points'])
        for left, right in request['windows'].values():
            wanted.update(range(left, right+1))
        path = ROOT/'book'/symbol/(session+'.jsonl')
        h = hashlib.sha256(); found = {}
        with path.open('rb') as stream:
            for seq, line in enumerate(stream):
                h.update(line)
                if seq in wanted:
                    found[seq] = raw_snapshot(seq, json.loads(line))
        assert wanted <= found.keys()
        r, f = ready[key], features[key]
        for seq in request['points']:
            i = int(np.searchsorted(r['seq'], seq))
            assert r['seq'][i] == seq
            raw = found[seq]
            assert raw['Buy1']['Price'] == f['bid'][i] and raw['Sell1']['Price'] == f['ask'][i]
            assert raw['Buy1']['Qty'] == f['bid_qty'][i] and raw['Sell1']['Qty'] == f['ask_qty'][i]
            assert datetime.fromisoformat(raw['CurrentPriceTime']).timestamp() == r['time_s'][i]
        windows = {name: raw_window([found[seq] for seq in range(left, right+1)]) for name, (left, right) in request['windows'].items()}
        name = f'生板小窓/{session}_{symbol}.json'
        save(name, dict(原本=str(path.relative_to(ROOT)), SHA256=h.hexdigest(),
                        参照行={seq: found[seq] for seq in sorted(request['points'])}, 判断前小窓=windows,
                        実行時刻ではなく最終約定の代理時計=True, 判断源泉との価格数量時計一致=True))
        output['|'.join(key)] = dict(保存先=name, 原本SHA256=h.hexdigest(), 原本必要行=len(found), 照合点数=len(request['points']))
    return output


def summarize(sessions: list[dict]) -> dict:
    """機能: 実損失の主因と、事前に実行できる対策三系統を短い資料にまとめる。

    引数: sessions(list[dict])。返り値: 説明用の要約(dict)。新規損益の有効性は主張しない。
    """
    notes = {
        ('2026-10-05_Day', 0): '両市場の下落とOFI売り支持はあったが、根拠から発注までに売値が3呼値不利化。その後は短期の反転を見送り、17pt幅で返済した。',
        ('2026-10-05_Day', 1): '両市場の下落・OFI売り支持は揃った。保有後は費用後黒字を一度も作れず、逆行のまま30分期限まで待った。',
        ('2026-10-05_Day', 2): 'TOPIXは上向きだが日経の15秒気配は横ばいでOFI支持も弱い。それでも許可し、後の最大評価益を17pt幅では保護できず場末に赤字返済。',
        ('2026-09-25_Night', 0): '追加判定では日経の15秒OFIが観測不足。逆OFIではないとして通過し、最大評価益は約9千円、30分期限で赤字。',
        ('2026-09-25_Night', 1): '両市場の買いOFIまで一致したが、その後の最大順行は0.5ptだけ。短期反転後も30分保持し10.5pt逆行で返済。',
        ('2026-09-25_Night', 2): '買い支持は揃い1.5ptまで順行したが、約1分後から短期反転を観測。16.5pt幅に届かない逆行は許容し30分期限で返済。',
        ('2026-09-22_Night', 0): '両300秒下落・両15秒OFI売り支持は揃った。後の順行は0.5ptにとどまり、短期反転後も保持して16.5pt幅で損切り。',
        ('2026-09-22_Night', 1): '同じ入口から7pt順行し、30分返済でも黒字。同じ短期反対は途中にも出たので、反対が一瞬見えたら必ず失敗と決められない。',
    }
    flat = []
    for session in sessions:
        for t in session['取引']:
            side = 1 if t['方向'] == '買い' else -1
            q = 'ask' if side == 1 else 'bid'
            roots = t['判断時に既知の旧入口根拠']
            bad = side*(t['入口判断'][q]-roots['TOPIX']['現在'][q])/.5
            flat.append(dict(セッション=session['セッション'], 組=t['組'], 方向=t['方向'],
                発注判断=t['入口判断']['最終約定時計'], 約定価格=t['入口価格'], 返済時計=t['返済約定']['最終約定時計'],
                返済価格=t['返済価格'], 返済理由=t['返済理由'], 費用後収支円=t['損益']['手数料後円'],
                最大清算評価益円=t['判断後の診断']['最大順行清算評価円'], 最大清算評価損円=t['判断後の診断']['最大逆行清算評価円'],
                両OFI支持=all(v['同方向OFI支持'] for v in t['判断時に既知の追加フィルター'].values()),
                根拠から発注までの自己不利化呼値=bad,
                入口根拠=[dict(銘柄=s, 時刻=v['現在']['最終約定時計'], 原本行=v['現在']['原本1始まり行'],
                              bid=v['現在']['bid'], bid数量=v['現在']['bid_qty'], ask=v['現在']['ask'], ask数量=v['現在']['ask_qty'],
                              進行300bp=v['進行300bp'], 進行15bp=v['進行15bp'], bid進行15呼値=v['bid進行15呼値'],
                              ask進行15呼値=v['ask進行15呼値'],
                              追加判定OFI比=t['判断時に既知の追加フィルター'][s]['フロー15秒']['ofi_ratio'],
                              追加判定OFI十分=t['判断時に既知の追加フィルター'][s]['フロー観測十分']) for s, v in roots.items()],
                解釈=notes[(session['セッション'], t['組'])]))
    losses = [t for t in flat if t['費用後収支円'] < 0]
    return dict(対象='TOPIX赤字上位3場の全8組。失敗事例を選んだ事後診断で、通常時の失敗確率ではない。',
        取引数=len(flat), 赤字取引数=len(losses), 黒字取引数=len(flat)-len(losses),
        収支円=sum(t['費用後収支円'] for t in flat),
        中値変動分円=sum(s['価格変動分円'] for s in sessions), 気配差分円=sum(s['気配差分円'] for s in sessions), 手数料円=sum(s['手数料円'] for s in sessions),
        両OFI支持のある赤字取引数=sum(t['両OFI支持'] for t in losses),
        FD反対15秒持続が保有中に成立した取引数=sum(t['判断後の診断']['後に観測された状態']['初めてFD反対15秒持続'] is not None for s in sessions for t in s['取引']),
        結論=[
            '入口で未来の反転は分からなかった。両市場の直近下落又は上昇は実際にあったが、その持続を保証する証拠ではなかった。',
            '7敗中5敗は両15秒OFIまで同方向を支持していた。支持必須へ変えるだけでは、この5敗は残る。',
            '中値変動の損失43万円に気配差6万円と手数料6,688円が加わった。手数料のみの赤字ではない。',
            '0.4%幅は16.5〜17ptあり、小さな順行が出た後の逆行を許した。旧FD管理も対象8組では確認が一度も成立しない。',
            '反転の瞬間は勝ち取引にもある。最大評価益での理想利確や、後の逆行を入口時に知った判定は対策として使えない。',
        ],
        予防案=[
            dict(案='入口で積極的な両OFI支持を要求', 因果条件='既存15秒OFIの双方の観測十分性と方向比0.1以上を必須にする。無効・欠測・中立を支持にしない。',
                 根拠='今回2敗は双方支持がなかった。ただし5敗と1勝にも双方支持があり、単独で解決しない。'),
            dict(案='根拠価格から走り過ぎた新規を見送る', 因果条件='自己発注判断のask又はbidが、入口根拠採用行の同じ約定側気配より不利1呼値超なら見送る。',
                 根拠='10/5朝の売りは根拠bid4135.5から判断bid4134.0へ3呼値動いていた。他7組では1呼値以内。'),
            dict(案='短期の進行失敗を保有中の別判断にする', 因果条件='既知30秒の両気配が自方向に逆行し、相手も逆行又は支持を失った状態を15秒・両参照更新付きで確認して返済する。保険の0.4%幅は維持。',
                 根拠='対象8組で旧FD反対の持続は不成立だった。一方で短期価格の反対は確認でき、幅に触れる前の崩れを扱える可能性がある。勝ちを刈る不利益も全30場で検証が必要。'),
        ],
        板の見方='OFIは板表示数量と最良価格の変化であり、実際の成行買い数量や売り数量そのものではない。同価格の減少後の回復も観測できるが、取消→再提示と約定→補充を区別する原本イベントはない。',
        表示行=flat, 将来情報を用いた新規売買なし=True, 新防止策損益の再生なし=True)


def main() -> None:
    """機能: 上位三赤字場の全取引を入口・保有・返済・費用へ分けて保存する。

    引数: なし。返り値: なし(None)。既存損益は読み取るだけで新規戦略の再生をしない。
    """
    socket.socket.connect = deny; socket.create_connection = deny
    meta = load('work/wave_v77/inputs/metadata.json')
    ready = {}; features = {}
    for kind, destination in [('ready', ready), ('features', features)]:
        for name in meta['input_paths'][kind]:
            material = load(name)
            destination.update({k: v for k, v in material.items() if k[0] in SESSIONS})
    grid = load('work/wave_v77/inputs/grids_delay5.pkl')
    state = load('work/wave_v78/prepared/signals_delay5.pkl')
    legacy = load('work/wave_v77/prepared/legacy_delay5.pkl')
    ledger = load(f'work/wave_v78/ledgers/{METHOD}.pkl')
    result = load(f'work/wave_v78/results/{METHOD}.json')
    requests = {}; sessions = []
    for session in SESSIONS:
        key = session, 'TOPIX'; r, f = ready[key], features[key]; orders = ledger[key]['orders']
        old_grid = np.arange(r['start']+300., r['limit']-300.+1e-6, 15.)
        width = max(2, math.ceil(meta['references']['|'.join(key)]['ref_open']['value']*.004/r['tick']-1e-10))*r['tick']
        trades = []
        for tr in ledger[key]['trades']:
            cid, ei, xi, side = map(int, tr[:4])
            entry_order = next(o for o in orders if int(o[2]) == cid and o[7] == 1)
            exit_order = next(o for o in orders if int(o[2]) == cid and o[7] == 0)
            di, xd = int(entry_order[1]), int(exit_order[1])
            candidate = next(row for row in legacy[key]['candidates'] if int(row[1]) == di)
            gi = int(candidate[0]); gt = old_grid[gi]
            new_g = int(np.searchsorted(grid[session]['grid'], r['time_s'][di], side='right'))-1
            assert np.searchsorted(r['time_s'], grid[session]['grid'][new_g], side='left') == di
            before = {}; fil = {}
            for symbol, source_i in [('TOPIX', int(candidate[3])), ('NK225', int(candidate[4]))]:
                pair = session, symbol; pr, pf = ready[pair], features[pair]
                before[symbol] = source_state(pr, pf, gt, source_i)
                fil[symbol] = filter_state(grid[session]['markets'][symbol], new_g, side)
                req = requests.setdefault(pair, dict(points=set(), windows={}))
                for label in ('現在', '過去300秒', '過去15秒'):
                    req['points'].add(before[symbol][label]['原本0始まり行'])
                now = before[symbol]['現在']['原本0始まり行']; short = before[symbol]['過去15秒']['原本0始まり行']
                req['windows'][f'組{cid}入口直前15秒'] = (short, now)
                source = int(grid[session]['markets'][symbol]['current']['index'][new_g])
                req['points'].add(int(pr['seq'][source]))
                assert pr['time_s'][source] < grid[session]['grid'][new_g]-5
            requests[key]['points'].update(int(r['seq'][i]) for i in (di, ei, xd, xi))
            assert side*before['TOPIX']['進行300bp'] >= 3 and side*before['NK225']['進行300bp'] >= 3
            assert side*before['TOPIX']['bid進行15呼値'] >= 1 and side*before['TOPIX']['ask進行15呼値'] >= 1
            assert side*before['NK225']['進行15bp'] >= 0
            assert not any(v['明確な逆OFI'] for v in fil.values())
            a, b = (side*fil[s]['進行300秒']['ret_bp'] for s in ('TOPIX', 'NK225'))
            assert min(a, b) >= .25*max(a, b)
            mid_gross = side*(f['mid'][xi]-f['mid'][ei])*tr[4]*1000
            spread = mid_gross-tr[9]
            decision_mid_gross = side*(f['mid'][xd]-f['mid'][di])*tr[4]*1000
            trades.append(dict(組=cid, 方向='買い' if side == 1 else '売り', 枚数=int(tr[4]),
                入口判断=point(r, f, di), 入口約定=point(r, f, ei), 返済判断=point(r, f, xd), 返済約定=point(r, f, xi),
                入口価格=float(tr[5]), 返済価格=float(tr[6]), 返済理由=REASONS[int(exit_order[6])],
                保有秒=float(r['time_s'][xi]-r['time_s'][ei]), 固定トレール幅pt=width,
                初期逆指値=float(tr[5]-side*width), 旧入口判断予定時刻=clock(gt), 追加フィルター判断予定時刻=clock(grid[session]['grid'][new_g]),
                判断時に既知の旧入口根拠=before, 判断時に既知の追加フィルター=fil,
                旧入口支持と追加OFI支持は別条件=True,
                損益=dict(中値変動分円=float(mid_gross), 売買気配差分円=float(spread), 価格損益円=float(tr[9]),
                          手数料円=float(tr[7]+tr[8]), 手数料後円=float(tr[10]),
                          判断同行中値から次観測中値への差額円=float(mid_gross-decision_mid_gross),
                          注意='中値変動分−気配差分−手数料＝実台帳収支。中値は約定可能価格ではない。判断次行の変化は中値変動分に含まれる補助内訳。'),
                判断後の診断=after_marks(r, f, grid[session], state[session], tr)))
        original = next(row for row in result['rows'] if row['session'] == session and row['symbol'] == 'TOPIX')
        assert sum(t['損益']['手数料後円'] for t in trades) == original['net']
        sessions.append(dict(セッション=session, 利益円=original['profit'], 損失円=original['loss'], 収支円=original['net'],
                             価格変動分円=sum(t['損益']['中値変動分円'] for t in trades),
                             気配差分円=sum(t['損益']['売買気配差分円'] for t in trades), 手数料円=sum(t['損益']['手数料円'] for t in trades), 取引=trades))
    save('TOPIX上位3赤字場の診断.json', dict(基準=METHOD, 対象商品='TOPIXミニ10枚・ラージの板を代用', セッション=sessions,
         根拠の区分='入口根拠は発注判断より前の採用原本行だけ。MFE/MAE・その後の反対化・出入り分解は事後説明。事後分類を入口へ逆流しない。',
         時刻限界=meta['時刻'], 予防案は全場の新規損益検証をまだしていない=True, 売買再実行=0, API取得=0))
    raw = extract_raw(requests, ready, features)
    save('生板照合の記録.json', dict(全点一致=True, 原本=raw, 新規売買再生=0, API取得=0))
    save('TOPIX根本原因と予防案.json', summarize(sessions))
    print(json.dumps(clean(dict(全取引数=sum(len(s['取引']) for s in sessions), 原本照合=raw,
                               場収支=[{k: s[k] for k in ('セッション', '収支円', '価格変動分円', '気配差分円', '手数料円')} for s in sessions])), ensure_ascii=False))


if __name__ == '__main__':
    main()

"""新条件を探索せず、E01の損益成立条件と時間的制約を既存台帳から測る。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import gzip
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True
JST = timezone(timedelta(hours=9))


def module(name: str, path: Path) -> object:
    """機能: 読取専用で既存の測定処理を読み込む。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def read(path: Path) -> object:
    """機能: 保存JSONを読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def payoff(values: list[float], weights: list[int] | None = None) -> dict:
    """機能: 組又は決済枚数単位の成功率・損益分岐成功率を求める。

    引数: values(list[float])は組又は1枚当たり損益、weights(list[int]|None)は枚数。
    返り値: 集計(dict)。損益ゼロは非ゼロ成功率の分母から除く。
    """
    x = np.asarray(values, float)
    w = np.ones(len(x), int) if weights is None else np.asarray(weights, int)
    plus, minus, zero = x > 0, x < 0, x == 0
    nw, nl, nz = int(w[plus].sum()), int(w[minus].sum()), int(w[zero].sum())
    gp, gl = float((x[plus]*w[plus]).sum()), float(-(x[minus]*w[minus]).sum())
    aw, al = gp/nw if nw else None, gl/nl if nl else None
    rate = nw/(nw+nl) if nw+nl else None
    threshold = al/(aw+al) if nw and nl else None
    nonzero_expectation = rate*aw-(1-rate)*al if nw and nl else (gp-gl)/(nw+nl) if nw+nl else 0.
    n = nw+nl+nz
    all_expectation = nonzero_expectation*(nw+nl)/n if n else 0.
    reconstructed = n*all_expectation
    assert abs(reconstructed-(gp-gl)) < 1e-6
    return dict(勝ち数=nw, 負け数=nl, ゼロ数=nz, 件数=n, 利益円=gp, 損失円=gl, 収支円=gp-gl,
        非ゼロ成功率=rate, 全件成功率=nw/n if n else None, 平均勝ち円=aw, 平均負け円=al,
        平均勝損比=aw/al if nw and nl else None, 損益分岐成功率=threshold,
        必要成功率との差=rate-threshold if threshold is not None else None,
        非ゼロ一件期待損益円=nonzero_expectation, 全件一件期待損益円=all_expectation,
        再構成収支円=reconstructed, ゼロ込み非ゼロ比=(nw+nl)/n if n else 0.)


def decomposition(before: dict, after: dict) -> dict:
    """機能: 平均収支の変化を成功頻度・勝ち額・負け額へ恒等分解する。

    引数: before/after(dict)。返り値: 差分の会計分解(dict)。因果効果ではない。
    """
    p0, p1 = before['非ゼロ成功率'], after['非ゼロ成功率']
    w0, w1 = before['平均勝ち円'], after['平均勝ち円']
    l0, l1 = before['平均負け円'], after['平均負け円']
    change = dict(成功頻度寄与円=(p1-p0)*(w0+w1+l0+l1)/2,
        平均勝ち額寄与円=(p0+p1)/2*(w1-w0), 平均負け額寄与円=-(1-(p0+p1)/2)*(l1-l0))
    delta = after['非ゼロ一件期待損益円']-before['非ゼロ一件期待損益円']
    assert abs(sum(change.values())-delta) < 1e-6
    return dict(**change, 平均収支変化円=delta, 注意='過去に観測した分布の会計恒等分解。成功率や金額を独立に変更できるという意味ではない。')


def distribution(values: list[float]) -> dict:
    """機能: 事後診断値の分位点を集計する。

    引数: values(list[float])。返り値: 分位点(dict)。
    """
    return {name: float(value) for name, value in zip(('10%', '25%', '中央値', '75%', '90%'), np.quantile(values,[.1,.25,.5,.75,.9]))} if values else {}


def main() -> None:
    """機能: 既存23場の損益性質を再構成して今回領域へ保存する。

    引数: なし。返り値: なし(None)。新戦略の再生・条件選択は行わない。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    diagnosis = read(HERE.parent / 'diagnosis/原因の証拠.json')
    loader = module('性質調査入力', HERE.parent / 'overlay/research.py')
    old = module('性質調査指標', ROOT / 'work/wave_v49/diagnosis/analyze.py')
    os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'numba_cache')
    inputs, ledgers = loader.load()
    names = sorted({key[0] for key in inputs})
    groups = dict(旧19=names[:19], 追加4=names[19:], 全23=names)
    statistics, paths = {}, []
    all_cycles = diagnosis['全取引']
    for label, sessions in groups.items():
        statistics[label] = {}
        for symbol in ('TOPIX', 'NK225'):
            campaigns = [r for r in all_cycles if r['銘柄']==symbol and r['セッション'] in sessions]
            trades = [t for key, ledger in ledgers.items() if key[1]==symbol and key[0] in sessions for t in ledger['trades']]
            mult = 1000 if symbol=='TOPIX' else 10
            cycle = payoff([r['収支円'] for r in campaigns])
            unit = payoff([t[2]*(t[5]-t[4])*mult for t in trades], [int(t[3]) for t in trades])
            assert abs(cycle['収支円']-unit['収支円']) < 1e-6
            result = dict(組単位=cycle, 決済枚数単位=unit, 場数=len(sessions), 一場組数=len(campaigns)/len(sessions),
                一場勝ち組数=cycle['勝ち数']/len(sessions), 一場負け組数=cycle['負け数']/len(sessions),
                一場利益円=cycle['利益円']/len(sessions), 一場損失円=cycle['損失円']/len(sessions), 一場収支円=cycle['収支円']/len(sessions))
            for outcome, condition in (('成功', lambda r:r['収支円']>0), ('失敗', lambda r:r['収支円']<0)):
                rows = [r for r in campaigns if condition(r)]
                result[outcome] = dict(組数=len(rows),
                    MFE_ATR=distribution([r['MFE_ATR'] for r in rows]), MAE_ATR=distribution([r['MAE_ATR'] for r in rows]),
                    保有分=distribution([r['保有分'] for r in rows]), 初回ATR=distribution([r['初回ATR'] for r in rows]),
                    初回ATR平均=float(np.mean([r['初回ATR'] for r in rows])) if rows else None,
                    初回1ATRリスク基準の平均実現R=float(np.mean([r['収支円']/(r['初回枚数']*r['初回ATR']*mult) for r in rows])) if rows else None,
                    MFE0_5ATR未達=sum(r['MFE_ATR']<.5 for r in rows), MFE1_5ATR未達=sum(r['MFE_ATR']<1.5 for r in rows),
                    入口開始条件失効=sum(r['開始条件失効'] for r in rows),
                    入口5分逆行=sum(r['変化逆行']['5'] for r in rows),
                    入口5分両市場逆方向=sum(r['変化不一致']['5'] for r in rows),
                    通常影待機合計分=sum(r['通常影待機']['待機分'] for r in rows),
                    通常影待機分=distribution([r['通常影待機']['待機分'] for r in rows]),
                    五分後も影待機中に同方向信号=sum(r['通常影待機']['5分待機後に同方向入口信号'] for r in rows),
                    影待機中に反対信号=sum(r['通常影待機']['待機中に反対入口信号'] for r in rows),
                    影待機中に元方向1ATR進行=sum(r['通常影待機']['旧方向最大値幅']>=r['初回ATR'] for r in rows))
            statistics[label][symbol] = result
    changes = {symbol: {unit: decomposition(statistics['旧19'][symbol][unit],statistics['追加4'][symbol][unit])
        for unit in ('組単位','決済枚数単位')} for symbol in ('TOPIX','NK225')}
    for key in sorted(ledgers):
        rows = [r for r in all_cycles if (r['セッション'],r['銘柄'])==key]
        ledger = ledgers[key]
        mult = ledger['config']['point_value']
        cycle = payoff([r['収支円'] for r in rows])
        unit = payoff([t[2]*(t[5]-t[4])*mult for t in ledger['trades']], [int(t[3]) for t in ledger['trades']])
        assert abs(cycle['収支円']-unit['収支円'])<1e-6
        paths.append(dict(セッション=key[0], 銘柄=key[1], 組単位=cycle, 決済枚数単位=unit))
    # ----------------------------------------
    # 入口の情報待ち時間は当時公開済みの指標だけから計算する。将来の山谷は定義しない。
    old.signals.set_root(ROOT)
    params = old.signals.legacy_spec(old.signals.specification())['params']
    models = {key:old.model(ready,params) for key,ready in inputs.items()}
    waiting = []
    for key, ready in sorted(inputs.items()):
        m = models[key]
        available = np.flatnonzero(np.isfinite(m['gap']) & np.isfinite(m['slope']))
        assert len(available)>0
        own_time = m['time_s'][available[0]]
        peer_key = key[0], 'NK225' if key[1]=='TOPIX' else 'TOPIX'
        peer = models[peer_key]
        peer_available = np.flatnonzero(np.isfinite(peer['gap']) & np.isfinite(peer['slope']))
        both_time = max(own_time,peer['time_s'][peer_available[0]]+60)
        allowed = old.signals.HIERARCHY._allowed(key,ready['time_s'],models,params)
        allowed_rows = np.flatnonzero(allowed!=0)
        ledger = ledgers[key]
        prepare = [r for r in ledger['entry_preparations']]
        delays = [(ready['time_s'][int(r[1])]-ready['time_s'][int(r[3])])/60 for r in prepare]
        first_fill = ready['time_s'][int(ledger['cycles'][0][1])] if ledger['cycles'] else None
        assert first_fill is None or first_fill >= both_time
        waiting.append(dict(セッション=key[0], 銘柄=key[1],
            セッション開始=datetime.fromtimestamp(ready['start'],JST).isoformat(),
            自市場EMA材料が揃うまで分=float((own_time-ready['start'])/60),
            相手遅延込みEMA材料が揃うまで分=float((both_time-ready['start'])/60),
            初めて両方向一致まで分=float((ready['time_s'][allowed_rows[0]]-ready['start'])/60) if len(allowed_rows) else None,
            初回約定まで分=float((first_fill-ready['start'])/60) if first_fill else None,
            注文準備から約定まで分=distribution(delays), 初回約定時刻=datetime.fromtimestamp(first_fill,JST).isoformat() if first_fill else None))
    clock_comparison = read(HERE.parent/'clock_search/時計変更の分解.json')['比較']['K04→K20']
    output = dict(全合格=True, 新条件探索数=0, API取得数=0, 場数=23, 集計=statistics, 変化の会計分解=changes,
        セッション別再構成=paths, 入口の待ち時間=waiting, 既実行の時計だけの介入比較=clock_comparison,
        注意=['損益分岐成功率は観測した勝幅/負幅から逆算した値で、未来の成功率予測ではない。',
              '成功率の分母からゼロ損益を除外する。全件成功率も併記し、収支再構成ではゼロ件数を含める。',
              '決済枚数は同じ組に属する相関した単位であり独立した試行数ではない。',
              'MFE/MAEは入口以後の値であり事後診断だけに使う。入口判定への追加は検証していない。',
              '新規抑制中の有利な価格変化を、そのまま逃した実現利益とはみなさない。',
              '既実行介入比較は同じ市場記録上の機械的比較であり、実市場の将来因果効果を証明しない。'])
    (HERE/'性質の数値.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    report(output)
    print(json.dumps(dict(変化の会計分解=changes,入口最短=min(r['相手遅延込みEMA材料が揃うまで分'] for r in waiting),
        入口最長=max(r['相手遅延込みEMA材料が揃うまで分'] for r in waiting)),ensure_ascii=False,indent=2))


def report(data: dict) -> None:
    """機能: 性質だけを短い日本語の報告へまとめる。

    引数: data(dict)。返り値: なし(None)。
    """
    lines = ['# E01の性質と今回崩れた部分', '', '新しい条件探しは行っていない。保存済み23場の会計と、既に実行した比較だけを用いた。', '',
        '**E01は高勝率型ではなく、少数の比較的大きな順行で多数の小損を回収する型。今回は小損の頻度が増え、回収できる成功率を下回った。**', '',
        '|単位|銘柄|期間|実成功率|必要成功率|平均勝ち円|平均負け円|平均勝損比|', '|---|---|---|---:|---:|---:|---:|---:|']
    for unit in ('組単位','決済枚数単位'):
        for symbol in ('TOPIX','NK225'):
            for period in ('旧19','追加4'):
                r = data['集計'][period][symbol][unit]
                lines.append(f"|{unit}|{symbol}|{period}|{r['非ゼロ成功率']:.1%}|{r['損益分岐成功率']:.1%}|{r['平均勝ち円']:,.0f}|{r['平均負け円']:,.0f}|{r['平均勝損比']:.2f}|")
    lines += ['', '成功率は損益ゼロを除く。組は最初の新規から全返済まで、枚数は部分返済も1枚ずつ数える。同じ建玉の複数枚は独立した当たり外れではない。', '',
        'TOPIXでは成功率低下に加え、平均の勝ち額も縮小した。勝った組の平均初回ATRは4.38→3.56pt、平均実現Rは2.07→1.90へ低下している。NKは平均勝損比が改善しているのに赤字となった。したがって「損小利大さえ成立すれば黒字」ではない。', '',
        '一場の負け組数はTOPIX2.58→5.50、NK2.79→4.75へ増加。TOPIXの勝ち組数は一場1.74→2.00へむしろ増えており、「勝つ機会が全くなくなった」のではなく、負けの増加と勝ち額縮小が回収を上回った。', '',
        '## 遅い入口と待機の意味', '',
        '- E01はセッションごとにEMAを初期化する。60本の長期EMAと3本差の傾きには最低63本の1分足が必要。足公開を開始120秒後、相手をさらに60秒遅らせるため、データが毎分揃っても両市場判定の材料が揃うのは開始65分後。20分の準備設定だけで取引できる設計ではない。',
        '- その後も両市場の保持方向一致、短期支持、新規トレーリングの反発/反落を待つ。方向がある程度続いた中腹へ入る設計で、早期転換検知を目的としたものではない。',
        '- 返済後に元の仮想時計が終わるまで待つため、目先の再試行を抑える一方、回復へ入り直せない場合がある。10月6日TOPIXの12:54〜15:35が後者。待機中の上昇22.5ptは観測事実であり、全幅を利益として取れた意味ではない。',
        '- 既実行の同じ15分休止同士の比較では、影損切りを1ATRから0.75ATRへ統一すると、TOPIX111→144組、NK113→133組へ増え、収支は52,500円・27,100円悪化した。待機を外すだけで解決する性質ではない。', '',
        '## 当時判断できたものと、後から分かるもの', '',
        '当時判断できるのは、確定済みEMA・直近価格変化・両市場の一致・それまでの実損益・保有経過時間。MFE（その取引中の最大順行）や、後で回復したかは当時には分からない。', '',
        '追加4場の負け41組は全て1.5ATR順行未達だった。旧19場の負けもTOPIX45/49組、NK52/53組が同じ型。負け組のMFE中央値もTOPIX0.55→0.55ATR、NK0.32→0.27ATRと似ている。新種の事故というより、従来からある失敗型が増えた。これを事前に区別できる観測特徴があるかは未確定。勝ち組が大きく順行していること自体も出口構造の影響を受けるため、入口で予測可能という証拠にはならない。', '',
        '## 注文方法だけで利益が生まれるか', '',
        '「上下が半々」と「どの時点でも将来の平均価格変化がゼロ」は別の仮定。上下が半々でも上昇幅が大きければ期待値は正になり、値動きに連続性や反復性があれば履歴で条件を分ける余地がある。', '',
        '一方、すべての利用情報で条件づけた価格変化の平均がゼロ、有限期間、保有量が有限、期待値が存在し、その市場価格で自己資金的に売買するという仮定なら、過去だけで変更する建玉の売買益の期待値はゼロ。ストップやトレーリングは損益分布を変えるが、この仮定の下で正の平均を生み出さない。実市場がこの仮定を満たすと断定したものではない。', '',
        '例えば上下1ずつの公平な歩行で、+2で利確・−1で損切りなら、成功率は1/3。勝ち幅が2倍でも平均は0になる。成功率と勝ち幅は独立に選べない。', '',
        '同じ価格で同枚数の両建てをすれば、買いの含み損益と売りの含み損益は相殺する。利益側だけを決済すると確定益は出るが、反対側の含み損と裸の方向リスクが残る。両建て自体は利益の源泉にならず、いつどの方向の純保有を増減するかが損益を決める。', '',
        '数値JSONには全46口座について「成功率×平均勝ち−失敗率×平均負け」から実収支を再構成した確認と、入口・影待機の分布を保存した。数学上の式と前提は「数理補足.md」を参照。', '']
    (HERE/'性質の要点.md').write_text('\n'.join(lines),encoding='utf8')


if __name__ == '__main__':
    main()

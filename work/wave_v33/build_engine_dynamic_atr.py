"""凍結済みv28注文器を読み、主玉の追跡ATRだけを差し替える別版を生成する。"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
source = (HERE.parent / 'wave_v28/engine_context.py').read_text(encoding='utf-8')


def replace(old: str, new: str) -> None:
    """機能: 原本の一意な位置だけをメモリー上で置換する。

    引数: old/new (str)。返り値: なし (None)。旧ファイルは変更しない。
    """
    global source
    assert source.count(old) == 1, old[:100]
    source = source.replace(old, new)


replace('"""入口信号と保有中の主方向を分離し、原本行順・次行執行で再生する建玉管理器。"""',
        '"""共通D273の主玉追跡幅だけを、固定A0又は保有中の公開済みAtで計算する。"""')
replace('\n\n@njit(cache=True)\ndef rounded', '''

ATR_COLUMNS = ['direction', 'initial_atr', 'current_atr', 'used_width_atr', 'extreme',
               'trail_active', 'trail_level', 'initial_risk', 'stop_level', 'pending_initial_atr',
               'current_atr_source_row', 'trail_source_row']


@njit(cache=True)
def rounded''')
replace('def simulate(time, price, atr, state, context, tick, start, end, us_open, par, detail, cap):',
        'def simulate(time, price, atr, trail_atr, state, context, tick, start, end, us_open, par, detail, cap, width_mode, observed_fill):')
replace('引数: time/price/atr/state/context/par (ndarray)、tick/start/end/us_open (float)、detail (bool)、cap (int)。',
        '引数: time/price/atr/trail_atr/state/context/par (ndarray)、tick/start/end/us_open (float)、detail/observed_fill (bool)、cap/width_mode (int)。')
replace('返り値: 返済台帳、組集計、資産曲線、注文台帳、検算値 (tuple[ndarray,...])。',
        '返り値: 旧5台帳と追跡ATRの全行診断 (tuple[ndarray,...])。')
replace('    n=len(price);pos=np.zeros((12000,5));trades=np.zeros((24000,11))', '''    n=len(price);pos=np.zeros((12000,5));trades=np.zeros((24000,11))
    atr_curve=np.full((n,12),np.nan) if detail else np.full((1,12),np.nan)
    current_atr=1.;current_atr_source=-1;trail_source=-1''')
replace('''        p=price[i];t=time[i]
        if not np.isfinite(p) or p<=0:
            continue''', '''        p=price[i];t=time[i]
        # ----------------------------------------
        # ATRの公開値を保有中だけ保持する。価格欠測でも既存線の約定や更新は行わない。
        if d!=0 and np.isfinite(trail_atr[i]) and trail_atr[i]>0:
            current_atr=max(trail_atr[i],tick*2);current_atr_source=i
        if not np.isfinite(p) or p<=0:
            if detail:
                atr_curve[i,:]=np.array([d,a if d else np.nan,current_atr if d else np.nan,
                    (a if width_mode==0 else current_atr) if d else np.nan,extreme if d else np.nan,
                    int(d!=0 and np.isfinite(main_level)),main_level,risk if d else np.nan,stop_level,
                    pending_atr if pending_d else np.nan,current_atr_source if d else -1,trail_source if d else -1])
            continue''')
replace('                fill=level', '                fill=p if observed_fill else level')
replace('base=realized;peak=0.;anchor=p if pending_market else pending_level;extreme=anchor',
        'base=realized;peak=0.;anchor=p if (observed_fill or pending_market) else pending_level;extreme=anchor')
replace('''            protected_floor=-risk;main_floor=np.nan
            entry_row=i;''', '''            protected_floor=-risk;main_floor=np.nan
            current_atr=a;current_atr_source=-1;trail_source=-1
            entry_row=i;''')
replace('''        if d!=0:
            e=equity-base;peak=max(peak,e);floor=-risk''', '''        if d!=0:
            # 当該行の新規約定ではA0から開始し、公開済みの当該行Atがあれば置き換える。
            # Atは追跡幅だけに使用し、リスク・始動・部分返済等のaを上書きしない。
            if np.isfinite(trail_atr[i]) and trail_atr[i]>0:
                current_atr=max(trail_atr[i],tick*2);current_atr_source=i
            e=equity-base;peak=max(peak,e);floor=-risk''')
replace('''                planned_main=rounded(extreme-d*width*a,tick,-d)
                if not np.isfinite(main_floor) or d*(planned_main-main_floor)>0:
                    main_floor=planned_main''', '''                width_atr=a if width_mode==0 else current_atr
                planned_main=rounded(extreme-d*width*width_atr,tick,-d)
                if not np.isfinite(main_floor) or d*(planned_main-main_floor)>0:
                    main_floor=planned_main;trail_source=i''')
replace('''    stats=np.array([realized,dd,maxlong,maxshort,maxgross,maxnet,max_error,min_equity,max_equity,''', '''        if detail:
            atr_curve[i,:]=np.array([d,a if d else np.nan,current_atr if d else np.nan,
                (a if width_mode==0 else current_atr) if d else np.nan,extreme if d else np.nan,
                int(d!=0 and np.isfinite(main_level)),main_level,risk if d else np.nan,stop_level,
                pending_atr if pending_d else np.nan,current_atr_source if d else -1,trail_source if d else -1])
    stats=np.array([realized,dd,maxlong,maxshort,maxgross,maxnet,max_error,min_equity,max_equity,''')
replace('    return trades[:tc],cycles[:cc],curve,orders[:oc],stats',
        '    return trades[:tc],cycles[:cc],curve,orders[:oc],stats,atr_curve')
source = source[:source.index('\ndef run(')] + '''
def run(ready: dict, state: np.ndarray, config: dict, detail: bool=False,
        context: np.ndarray | None=None, width_mode: int=0, observed_fill: bool=False,
        trail_atr: np.ndarray | None=None) -> dict:
    """機能: 共通D273の追跡幅だけを固定A0又は現在Atで更新する。

    引数: ready/config (dict)、state/context (ndarray[int8]|None)、detail/observed_fill (bool)、width_mode (int,0固定/1現在)。
    trail_atr (一次元浮動小数ndarray|None) は原本行対応の公開済み追跡ATR。Noneならready['atr']。
    返り値: 旧trades/cycles/curve/orders/statsとatr_curveの辞書 (dict)。旧5結果の列・単位は不変。
    A0は新規準備時のready['atr']。入口、1A0初期組予算、1.5A0始動、2A0部分返済等は不変。
    保有中Atは有限正値のみを採用し2呼値以上へ補正、欠損は直前を維持、最初はA0。
    追跡線は利益方向へだけ進め、当該行の価格判断後に設置するため次行から有効。
    observed_fill=Trueは新規・部分利確・損切り・追跡等の全約定を現観測pにする。
    ATR列の公開時刻の因果性は呼出し側で保証する。この関数は未来行を参照しない。
    """
    n=len(ready['last'])
    if n<1 or not isinstance(state,np.ndarray) or state.ndim!=1 or len(state)!=n or not np.isin(state,(-1,0,1)).all():
        raise ValueError('入口は原本行対応の一次元-1/0/1配列に限ります')
    if type(width_mode) is not int or width_mode not in (0,1):
        raise ValueError('追跡幅方式は整数0=固定A0又は1=現在Atに限ります')
    if not isinstance(observed_fill,(bool,np.bool_)):
        raise ValueError('観測約定は真偽値で指定してください')
    if trail_atr is None:
        trail_atr=ready['atr']
    if not isinstance(trail_atr,np.ndarray) or trail_atr.ndim!=1 or len(trail_atr)!=n or not np.issubdtype(trail_atr.dtype,np.floating):
        raise ValueError('追跡ATRは原本行対応の一次元浮動小数配列に限ります')
    if context is None:
        context=state
    elif not isinstance(context,np.ndarray) or context.dtype!=np.int8 or context.ndim!=1 or len(context)!=n or not np.isin(context,(-1,0,1)).all():
        raise ValueError('保有管理方向は原本行対応のndarray[int8]、-1/0/1に限ります')
    cap=config['audit_cap']
    if cap not in (10,20) or config['initial_qty']!=cap//2:
        raise ValueError('D273はTOPIX上限10/初回5、NK上限20/初回10に限ります')
    required={'entry_atr':.25,'stop_atr':1.,'main_trail':3.,'split_target':2.,
              'activation_atr':1.5,'timeout_min':360.,'cooldown_min':5.,'ttl_seconds':300.,
              'entry_mode':1,'entry_cutoff_min':5.,'warmup_min':20.,'after_open_factor':1.}
    disabled=('add_mode','add_qty','hedge_ratio','cover_add','reverse_mode','lock_fraction','neutral_min','us_mode',
              'tighten_atr','breakeven_atr','failure_min','signal_exit','max_same_losses','session_budget_r','risk_yen','session_budget_yen')
    if any(config.get(k)!=v for k,v in required.items()) or any(config.get(k)!=0 for k in disabled):
        raise ValueError('追跡ATR以外は共通D273から変更できません')
    par=np.array([config[k] for k in PARAMS],dtype=float)
    values=simulate(ready['time_s'],ready['last'],ready['atr'],trail_atr,state,context,ready['tick'],
                    ready['start'],ready['limit'],ready['us_open'],par,detail,cap,width_mode,observed_fill)
    return dict(zip(['trades','cycles','curve','orders','stats','atr_curve'],values))
'''
(HERE / 'engine_dynamic_atr.py').write_text(source, encoding='utf-8')
print('主追跡ATRの別版を作成。旧コード変更なし。')

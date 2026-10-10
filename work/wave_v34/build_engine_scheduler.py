"""凍結済み v33 注文器を読取り、新規準備だけに許可を付けた別版を生成する。"""

from pathlib import Path
import hashlib


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'wave_v33/engine_dynamic_atr.py'
SOURCE_SHA = 'cf4381e04704ae77d2bcaa824e7f66bad092648276faf40de014fdfd974ec35b'


def replace_once(text: str, before: str, after: str) -> str:
    """機能: 元の一箇所だけを置換し、予期しない元コード差を拒否する。

    引数: text/before/after (str)。返り値: 置換後本文 (str)。
    """
    assert text.count(before) == 1, before[:160]
    return text.replace(before, after, 1)


def build() -> str:
    """機能: 新規準備の許可条件と起点の記録だけを追加する。

    引数: なし。返り値: 生成コード (str)。元ソースは変更しない。
    """
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA
    text = SOURCE.read_text(encoding='utf-8')
    text = replace_once(text, '"""共通D273の主玉追跡幅だけを、固定A0又は保有中の公開済みAtで計算する。"""',
        '"""共通D273の新規準備を許可行だけに制限し、既存注文・返済の順序を維持する。"""')
    text = replace_once(text, '\n\n@njit(cache=True)\ndef rounded', '''

PREPARE_COLUMNS = ['prepare_id', 'row', 'side', 'level', 'initial_atr', 'expiry_time', 'qty']
ENTRY_PREPARATION_COLUMNS = ['campaign', 'fill_row', 'prepare_id', 'prepare_row']


@njit(cache=True)
def rounded''')
    text = replace_once(text,
        'def simulate(time, price, atr, trail_atr, state, context, tick, start, end, us_open, par, detail, cap, width_mode, observed_fill):',
        'def simulate(time, price, atr, trail_atr, state, context, tick, start, end, us_open, par, detail, cap, width_mode, observed_fill, prepare_allow):')
    text = replace_once(text,
        '引数: time/price/atr/trail_atr/state/context/par (ndarray)、tick/start/end/us_open (float)、detail/observed_fill (bool)、cap/width_mode (int)。\n    返り値: 旧5台帳と追跡ATRの全行診断 (tuple[ndarray,...])。',
        '引数: time/price/atr/trail_atr/state/context/par/prepare_allow (ndarray)、tick/start/end/us_open (float)、detail/observed_fill (bool)、cap/width_mode (int)。\n    返り値: 旧6結果と新設準備・約定元準備の記録 (tuple[ndarray,...])。')
    text = replace_once(text, 'n=len(price);pos=np.zeros((12000,5));trades=np.zeros((24000,11))',
        '''n=len(price);pos=np.zeros((12000,5));trades=np.zeros((24000,11))
    # 新設は一行に最大一件。追跡更新でこのID・行は変更しない。
    prepare_events=np.zeros((n,7));prepare_count=0
    entry_preparations=np.zeros((2000,4));entry_prepare_count=0
    pending_prepare_id=-1;pending_prepare_row=-1''')
    text = replace_once(text,
        'order_source=pending_row;pending_d=0;next_add=anchor+d*par[5]*a*(-1 if int(par[4])==2 else 1)',
        '''order_source=pending_row
            if entry_prepare_count>=len(entry_preparations):
                raise ValueError('約定元準備の記録上限を超えました')
            entry_preparations[entry_prepare_count,:]=np.array([campaign,i,pending_prepare_id,pending_prepare_row])
            entry_prepare_count+=1
            pending_d=0;next_add=anchor+d*par[5]*a*(-1 if int(par[4])==2 else 1)''')
    text = replace_once(text,
        'if not pending_d and not session_halted and t>=start+par[32]*60 and t<end-par[31]*60 and t>=last_exit+par[26]*60 and not paused:',
        '''# 許可は新しい準備にだけ必要。既設注文の更新・取消・約定へは作用しない。
            if prepare_allow[i] and not pending_d and not session_halted and t>=start+par[32]*60 and t<end-par[31]*60 and t>=last_exit+par[26]*60 and not paused:''')
    text = replace_once(text,
        'elif not np.isfinite(session_budget) and par[35]>0:\n                        session_budget=par[35]*pending_qty*par[2]*pending_atr',
        '''elif not np.isfinite(session_budget) and par[35]>0:
                        session_budget=par[35]*pending_qty*par[2]*pending_atr
                    if pending_d:
                        pending_prepare_id=prepare_count;pending_prepare_row=i
                        prepare_events[prepare_count,:]=np.array([prepare_count,i,pending_d,pending_level,pending_atr,pending_until,pending_qty])
                        prepare_count+=1''')
    text = replace_once(text,
        'return trades[:tc],cycles[:cc],curve,orders[:oc],stats,atr_curve',
        'return trades[:tc],cycles[:cc],curve,orders[:oc],stats,atr_curve,prepare_events[:prepare_count],entry_preparations[:entry_prepare_count]')
    text = replace_once(text,
        'trail_atr: np.ndarray | None=None) -> dict:',
        'trail_atr: np.ndarray | None=None, prepare_allow: np.ndarray | None=None) -> dict:')
    text = replace_once(text,
        '返り値: 旧trades/cycles/curve/orders/statsとatr_curveの辞書 (dict)。旧5結果の列・単位は不変。',
        '''prepare_allow (一次元ndarray[bool]|None) は新規準備の許可行。Noneは全行許可。
    返り値: 旧6結果とprepare_events、entry_preparationsの辞書 (dict)。旧6結果の列・単位は不変。
    許可がFalseでも未約定の既設注文は存続し、通常の追跡更新・取消・約定を行う。
    許可がTrueでも保有中、自身の全返済後5分、開始/場末等の通常条件では新設しない。
    仮想運転は別にwidth_mode=0、prepare_allow=Noneで因果再生し、その新設行だけを許可する。
    仮想の約定行・将来の返済行を実側の過去約定へコピーしてはならない。
    prepare_idは各運転内の新設連番で、追跡更新の注文元行とは別に固定する。''')
    text = replace_once(text,
        "n=len(ready['last'])\n    if n<1", 
        """n=len(ready['last'])
    if prepare_allow is None:
        prepare_allow=np.ones(n,dtype=np.bool_)
    elif not isinstance(prepare_allow,np.ndarray) or prepare_allow.dtype!=np.bool_ or prepare_allow.ndim!=1 or len(prepare_allow)!=n:
        raise ValueError('新規準備許可は原本行対応の一次元ndarray[bool]に限ります')
    if n<1""")
    text = replace_once(text,
        "ready['start'],ready['limit'],ready['us_open'],par,detail,cap,width_mode,observed_fill)",
        "ready['start'],ready['limit'],ready['us_open'],par,detail,cap,width_mode,observed_fill,prepare_allow)")
    text = replace_once(text,
        "return dict(zip(['trades','cycles','curve','orders','stats','atr_curve'],values))",
        "return dict(zip(['trades','cycles','curve','orders','stats','atr_curve','prepare_events','entry_preparations'],values))")
    return text


def main() -> None:
    """機能: 新規版を保存し元と生成版の指紋を表示する。

    引数: なし。返り値: なし (None)。
    """
    destination = HERE / 'engine_scheduler.py'
    destination.write_text(build(), encoding='utf-8')
    print('元', SOURCE_SHA, '新', hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()

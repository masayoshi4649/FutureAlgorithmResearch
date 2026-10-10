"""旧注文器を変更せず、次行有効計画の記録だけを新しい複写へ追加する。"""

from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'wave_v34' / 'engine_scheduler.py'
TARGET = HERE / 'engine_shadow_plan.py'

PLAN_COLUMNS = [
    'direction', 'campaign', 'initial_atr', 'anchor', 'initial_risk',
    'entry_row', 'entry_time', 'shadow_qty', 'shadow_realized', 'campaign_base',
    'extreme', 'split_done', 'stop_level', 'trail_level', 'split_level',
    'stop_market', 'trail_market', 'split_market', 'pending_action', 'action_row',
    'stop_reason', 'pending_direction', 'pending_level', 'pending_expiry',
    'pending_atr', 'pending_qty', 'pending_market', 'pending_source_row',
    'pending_prepare_id', 'pending_prepare_row', 'session_halted', 'last_exit',
    'effective_qty', 'plan_source_row', 'trail_source_row', 'current_atr',
    'current_atr_source_row',
]


def build() -> dict:
    """機能: 唯一の旧コードから計画記録だけを加えた新ソースを生成する。

    引数: なし。返り値: 旧新SHAと置換数の証跡 (dict)。
    """
    original = SOURCE.read_bytes()
    text = original.decode('utf-8-sig').replace('\r\n', '\n')
    changes = []

    def replace(before: str, after: str) -> None:
        """機能: 一意な生成位置を検査して置換する。

        引数: before/after (str)。返り値: なし (None)。
        """
        nonlocal text
        assert text.count(before) == 1, before
        text = text.replace(before, after)
        changes.append(before)

    replace('PREPARE_COLUMNS = ', 'PLAN_COLUMNS = ' + repr(PLAN_COLUMNS) + '\n\nPREPARE_COLUMNS = ')
    replace('    n=len(price);pos=np.zeros((12000,5));trades=np.zeros((24000,11))',
            '    n=len(price);pos=np.zeros((12000,5));trades=np.zeros((24000,11))\n'
            '    plans=np.full((n,37),np.nan)')
    replace('        if not np.isfinite(p) or p<=0:\n',
            '        if not np.isfinite(p) or p<=0:\n'
            '            if i>0: plans[i,:]=plans[i-1,:]\n')
    marker = '    stats=np.array([realized,dd,maxlong,maxshort,maxgross,maxnet,max_error,min_equity,max_equity,'
    record = '''        # ----------------------------------------
        # 当該行の全処理後に有効な注文計画だけを記録する。次行以降の約定は含めない。
        plans[i,:]=np.array([d,campaign,a,anchor,risk,entry_row,entry_t,inv[0],realized,base,
            extreme,int(split_done),stop_level,main_level,split_level,int(market_flags[0]),
            int(market_flags[1]),int(market_flags[5]),pending_action,action_row,stop_reason,
            pending_d,pending_level,pending_until,pending_atr,pending_qty,int(pending_market),
            pending_row,pending_prepare_id,pending_prepare_row,int(session_halted),last_exit,
            effective_qty,i,trail_source,current_atr,current_atr_source])
'''
    replace(marker, record + marker)
    replace('entry_preparations[:entry_prepare_count]\n', 'entry_preparations[:entry_prepare_count],plans\n')
    replace("'prepare_events','entry_preparations'],values))", "'prepare_events','entry_preparations','plans'],values))")
    text = text.replace('"""共通D273の新規準備を許可行だけに制限し、既存注文・返済の順序を維持する。"""',
                        '"""固定A0影の旧結果を保持し、各行後の次行有効注文計画を追加記録する。"""')
    TARGET.write_text(text, encoding='utf-8', newline='\n')
    assert SOURCE.read_bytes() == original
    result = dict(旧ソース=str(SOURCE),旧SHA256=hashlib.sha256(original).hexdigest(),
                  新ソース=str(TARGET),新SHA256=hashlib.sha256(TARGET.read_bytes()).hexdigest(),
                  置換数=len(changes),追加列=PLAN_COLUMNS,
                  意味='行iの計画は行i処理終了時点。実行側はiより後の観測価格とだけ組み合わせる。')
    (HERE / 'shadow_plan_build.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__ == '__main__':
    build()

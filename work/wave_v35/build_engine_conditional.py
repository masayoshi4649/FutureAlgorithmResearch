"""凍結済み注文器の追跡幅部分だけを置換し、条件付き短縮を別ファイルへ生成する。"""

from pathlib import Path
import hashlib

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'wave_v34/engine_scheduler.py'


def replace_once(text: str, old: str, new: str) -> str:
    """機能: 一意な置換点だけを許可し、元版との差を限定する。

    引数: text/old/new (str)。返り値: 置換した全文 (str)。
    """
    assert text.count(old) == 1, old[:100]
    return text.replace(old, new)


def main() -> None:
    """機能: 元版の指紋を検証して条件付き注文器を生成する。

    引数: なし。返り値: なし (None)。元版は変更しない。
    """
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == 'b5fbe14ced6c813c48e9ef23ac010bb25fecad0163501d5bbee8f4c416427cf3'
    text = SOURCE.read_text(encoding='utf-8')
    text = replace_once(text, '"""共通D273の新規準備を許可行だけに制限し、既存注文・返済の順序を維持する。"""',
                        '"""固定A0候補を毎行維持し、現在ATRによる追跡短縮だけを因果条件で追加する。"""')
    text = replace_once(text, "ENTRY_PREPARATION_COLUMNS = ['campaign', 'fill_row', 'prepare_id', 'prepare_row']", """ENTRY_PREPARATION_COLUMNS = ['campaign', 'fill_row', 'prepare_id', 'prepare_row']

CONDITIONAL_COLUMNS = ['direction', 'deterioration_direction', 'deterioration_source_row',
    'shortening_enabled', 'initial_atr', 'current_atr', 'used_width_atr', 'prior_level',
    'fixed_candidate', 'short_candidate', 'selected_candidate', 'final_level', 'advanced',
    'advance_kind', 'current_atr_source_row', 'line_source_row', 'line_evidence_row',
    'line_evidence_source_row']
TRAIL_EVENT_COLUMNS = ['row', 'campaign', 'direction', 'prior_level', 'fixed_candidate',
    'short_candidate', 'final_level', 'advance_kind', 'initial_atr', 'current_atr',
    'used_width_atr', 'current_atr_source_row', 'evidence_row', 'evidence_source_row',
    'evidence_direction']
ADVANCE_KINDS = {1: '固定A0候補', 2: '常時最小幅の追加短縮', 3: '悪化根拠による追加短縮'}""")
    text = replace_once(text, 'width_mode, observed_fill, prepare_allow):',
                        'width_mode, observed_fill, prepare_allow, deterioration, deterioration_source):')
    text = replace_once(text, 'time/price/atr/trail_atr/state/context/par/prepare_allow (ndarray)',
                        'time/price/atr/trail_atr/state/context/par/prepare_allow/deterioration/deterioration_source (ndarray)')
    text = replace_once(text, '旧6結果と新設準備・約定元準備の記録 (tuple[ndarray,...])',
                        '旧8結果と条件詳細・追跡進行イベント (tuple[ndarray,...])')
    text = replace_once(text, '    current_atr=1.;current_atr_source=-1;trail_source=-1', '''    current_atr=1.;current_atr_source=-1;trail_source=-1
    conditional_curve=np.full((n,18),np.nan) if detail else np.full((1,18),np.nan)
    trail_events=np.zeros((n,15));trail_event_count=0
    line_evidence_row=-1;line_evidence_source=-1''')
    text = replace_once(text, '        p=price[i];t=time[i]', '''        p=price[i];t=time[i]
        prior_main=main_floor if d else np.nan
        fixed_candidate=np.nan;short_candidate=np.nan;planned_main=np.nan
        advanced=0;advance_kind=0
        shortening=(d!=0 and (width_mode==1 or (width_mode==2 and deterioration[i]==-d)))''')
    text = replace_once(text, '            current_atr=a;current_atr_source=-1;trail_source=-1', '''            current_atr=a;current_atr_source=-1;trail_source=-1
            line_evidence_row=-1;line_evidence_source=-1''')
    # ----------------------------------------
    # 固定候補を条件の外に保ち、追加短縮の許可だけを悪化方向で制御する。
    text = replace_once(text, '''                width_atr=a if width_mode==0 else current_atr
                planned_main=rounded(extreme-d*width*width_atr,tick,-d)
                if not np.isfinite(main_floor) or d*(planned_main-main_floor)>0:
                    main_floor=planned_main;trail_source=i
                main_level=main_floor''', '''                shortening=(width_mode==1 or (width_mode==2 and deterioration[i]==-d))
                width_atr=min(a,current_atr) if shortening else a
                # 条件が偽でも固定候補は必ず更新する。既設の短縮線も緩めない。
                fixed_candidate=rounded(extreme-d*width*a,tick,-d)
                planned_main=fixed_candidate;candidate_kind=1
                if shortening:
                    short_candidate=rounded(extreme-d*width*width_atr,tick,-d)
                    if d*(short_candidate-fixed_candidate)>0:
                        planned_main=short_candidate;candidate_kind=2 if width_mode==1 else 3
                if not np.isfinite(main_floor) or d*(planned_main-main_floor)>0:
                    prior_main=main_floor;main_floor=planned_main;trail_source=i
                    advanced=1;advance_kind=candidate_kind
                    line_evidence_row=i if candidate_kind==3 else -1
                    line_evidence_source=int(deterioration_source[i]) if candidate_kind==3 else -1
                    trail_events[trail_event_count,:]=np.array([i,campaign,d,prior_main,fixed_candidate,
                        short_candidate,main_floor,candidate_kind,a,current_atr,width_atr,current_atr_source,
                        line_evidence_row,line_evidence_source,int(deterioration[i]) if candidate_kind==3 else 0])
                    trail_event_count+=1
                main_level=main_floor''')
    # ----------------------------------------
    # 旧ATR列の構造を保ち、追加記録で候補と有効線・根拠を区別する。
    text = text.replace('(a if width_mode==0 else current_atr) if d else np.nan',
                        '(min(a,current_atr) if (width_mode==1 or (width_mode==2 and deterioration[i]==-d)) else a) if d else np.nan')
    missing_end = '''pending_atr if pending_d else np.nan,current_atr_source if d else -1,trail_source if d else -1])
            continue'''
    text = replace_once(text, missing_end, '''pending_atr if pending_d else np.nan,current_atr_source if d else -1,trail_source if d else -1])
                conditional_curve[i,:]=np.array([d,deterioration[i],deterioration_source[i],int(shortening),
                    a if d else np.nan,current_atr if d else np.nan,
                    (min(a,current_atr) if shortening else a) if d else np.nan,
                    prior_main,np.nan,np.nan,np.nan,main_floor if d else np.nan,0,0,
                    current_atr_source if d else -1,trail_source if d else -1,
                    line_evidence_row if d else -1,line_evidence_source if d else -1])
            continue''')
    end = '''pending_atr if pending_d else np.nan,current_atr_source if d else -1,trail_source if d else -1])
    stats='''
    text = replace_once(text, end, '''pending_atr if pending_d else np.nan,current_atr_source if d else -1,trail_source if d else -1])
            shortening=(d!=0 and (width_mode==1 or (width_mode==2 and deterioration[i]==-d)))
            conditional_curve[i,:]=np.array([d,deterioration[i],deterioration_source[i],int(shortening),
                a if d else np.nan,current_atr if d else np.nan,
                (min(a,current_atr) if shortening else a) if d else np.nan,
                prior_main,fixed_candidate,short_candidate,planned_main,main_floor if d else np.nan,
                advanced,advance_kind,current_atr_source if d else -1,trail_source if d else -1,
                line_evidence_row if d else -1,line_evidence_source if d else -1])
    stats=''')
    text = replace_once(text, 'prepare_events[:prepare_count],entry_preparations[:entry_prepare_count]',
                        'prepare_events[:prepare_count],entry_preparations[:entry_prepare_count],conditional_curve,trail_events[:trail_event_count]')
    text = replace_once(text, 'trail_atr: np.ndarray | None=None, prepare_allow: np.ndarray | None=None) -> dict:',
                        '''trail_atr: np.ndarray | None=None, prepare_allow: np.ndarray | None=None,
        deterioration: np.ndarray | None=None, deterioration_source: np.ndarray | None=None) -> dict:''')
    start = text.index('    """機能: 共通D273の追跡幅だけを固定A0又は現在Atで更新する。', text.index('def run('))
    end_doc = text.index('    n=len(ready[\'last\'])', start)
    text = text[:start] + '''    """機能: 共通D273の固定追跡へ、常時又は悪化確認時だけ最小ATR幅を追加する。

    引数: ready/config (dict)、state/context (ndarray[int8]|None)、detail/observed_fill (bool)。
    width_mode (int) は0固定A0、1常時min(A0,At)、2悪化方向が保有方向の逆の時だけmin。
    trail_atr (一次元浮動小数ndarray|None) は公開済みAt。Noneはready['atr']。
    prepare_allow (一次元ndarray[bool]|None) は新規準備だけの許可。Noneは全行。
    deterioration (一次元ndarray[int8]|None) は悪化を認めた価格方向。Noneは全中立。
    deterioration_source (一次元ndarray[int64]|None) は悪化根拠の参照原本行。
    非中立では0以上かつ当該行以下。Noneは当該行を記録し、外部特徴の因果性は呼出側が保証する。
    返り値: 旧8結果、conditional_curveとtrail_events (dict[str,ndarray])。
    旧8結果の列・単位は不変。追加詳細曲線はdetail=Falseで一行に省略、進行イベントは常に保存。
    初期A0・予算・1.5A0始動・2A0部分返済・全返済後5分等は従来D273に固定。
    Atは初回A0、有限正値だけ2呼値以上で採用し、欠測は直前値を維持する。
    固定3A0候補は毎有効保有行で更新し、条件は追加短縮だけを許可する。既設線を緩めない。
    現行の既設注文を先に執行した後で線を更新し、新線は次原本行から有効。
    observed_fill=Trueは新規・部分・全返済をすべて現在観測価格にする。
    影は別のmode0通常運転でAtと悪化条件に依存せず、そのfresh準備行を許可列とする。
    """
''' + text[end_doc:]
    text = replace_once(text, "    n=len(ready['last'])", """    n=len(ready['last'])
    if deterioration is None:
        deterioration=np.zeros(n,dtype=np.int8)
    elif not isinstance(deterioration,np.ndarray) or deterioration.dtype!=np.int8 or deterioration.ndim!=1 or len(deterioration)!=n or not np.isin(deterioration,(-1,0,1)).all():
        raise ValueError('悪化方向は原本行対応の一次元ndarray[int8]、-1/0/1に限ります')
    if deterioration_source is None:
        deterioration_source=np.where(deterioration!=0,np.arange(n),-1).astype(np.int64)
    elif not isinstance(deterioration_source,np.ndarray) or deterioration_source.dtype!=np.int64 or deterioration_source.ndim!=1 or len(deterioration_source)!=n:
        raise ValueError('悪化根拠行は原本行対応の一次元ndarray[int64]に限ります')
    if np.any(deterioration_source>np.arange(n)) or np.any(deterioration_source < -1) or np.any((deterioration!=0)&(deterioration_source<0)):
        raise ValueError('悪化根拠に未来行又は非中立の不明行は指定できません')""")
    text = replace_once(text, 'width_mode not in (0,1):', 'width_mode not in (0,1,2):')
    text = replace_once(text, "raise ValueError('追跡幅方式は整数0=固定A0又は1=現在Atに限ります')",
                        "raise ValueError('追跡幅方式は整数0=固定A0/1=常時最小/2=悪化時最小に限ります')")
    text = replace_once(text, 'par,detail,cap,width_mode,observed_fill,prepare_allow)',
                        'par,detail,cap,width_mode,observed_fill,prepare_allow,deterioration,deterioration_source)')
    text = replace_once(text, "'stats','atr_curve','prepare_events','entry_preparations'],values)",
                        "'stats','atr_curve','prepare_events','entry_preparations','conditional_curve','trail_events'],values)")
    (HERE / 'engine_conditional.py').write_text(text, encoding='utf-8')
    print('条件付き追跡注文器を別版へ生成しました。')


if __name__ == '__main__':
    main()

"""凍結した旧実装から、二つの影と実口座を同じ観測順で接続する。"""
from pathlib import Path
import ast
import copy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def replace_once(text, old, new):
    """
    機能: 生成元の一致を検証して一箇所だけ置換する。
    引数: text/old/new(str)。
    返り値: str の置換結果。
    """
    assert text.count(old) == 1, (old, text.count(old))
    return text.replace(old, new, 1)


def shadow_source():
    """
    機能: 旧出口影へ過去B00による幅短縮と静観の接続口を追加する。
    引数: なし。
    返り値: str の生成コード。通常影には短縮を適用しない。
    """
    text = (ROOT / 'work/wave_v67/engine_shadow.py').read_text(encoding='utf-8')
    text = text[:text.index('\ndef run(')]
    text = replace_once(text, 'min_delay_seconds, session_close):',
        'min_delay_seconds, session_close, raw_bad, raw_source, raw_valid, dynamic, dynamic_activation, dynamic_width, quiet, quiet_force, quiet_not_before):')
    text = replace_once(text, 'n=len(price);pos=',
        'dynamic_events=np.zeros((12000,7));dynamic_count=0;narrowed=False\n    n=len(price);pos=')
    text = replace_once(text, 'fill=anchor;open_side=d;', 'narrowed=False\n                    fill=anchor;open_side=d;')
    text = replace_once(text, 'execution_plans[i,:]=effective',
        'if quiet[i] or quiet_force[i] or (pending_prepare_row>=0 and time[pending_prepare_row]<quiet_not_before[i]):\n            pending_d=0\n            effective[21]=0.\n        if quiet_force[i] and d!=0:\n            effective[18]=71.;effective[19]=i-1\n        execution_plans[i,:]=effective')
    text = replace_once(text, 'if prepare_allow[i] and not pending_d',
        'if prepare_allow[i] and not quiet[i] and not quiet_force[i] and not pending_d')
    text = replace_once(text, 'if np.isfinite(par[3]) and d*(extreme-anchor)>=par[18]*a:',
        'if dynamic and not narrowed and raw_valid[i] and raw_bad[i]==-d and raw_source[i]>entry_row and raw_source[i]<=i and d*(extreme-anchor)>=dynamic_activation*a:\n                narrowed=True\n                old_width=par[3]\n                if par[19]>0 and d*(extreme-anchor)>=par[19]*a: old_width=min(old_width,par[20])\n                if t>=us_open: old_width*=par[30]\n                if dynamic_count>=len(dynamic_events): raise ValueError("幅短縮証跡の保存上限です")\n                dynamic_events[dynamic_count,:]=np.array([i,campaign,raw_source[i],d,d*(extreme-anchor)/a,old_width,min(old_width,dynamic_width)])\n                dynamic_count+=1\n            if np.isfinite(par[3]) and d*(extreme-anchor)>=par[18]*a:')
    text = replace_once(text, 'width_atr=a if width_mode==0 else current_atr',
        'if narrowed: width=min(width,dynamic_width)\n                width_atr=a if width_mode==0 else current_atr')
    text = replace_once(text, 'plans,execution_plans\n', 'plans,execution_plans,dynamic_events[:dynamic_count]\n')
    return text


class Names(ast.NodeTransformer):
    """変数名を影ごとに独立させ、共有入力だけ同じ配列へ接続する。"""
    def __init__(self, mapping):
        """
        機能: 名前の対応表を保持する。
        引数: mapping(dict[str,str])。
        返り値: なし。
        """
        self.mapping = mapping

    def visit_Name(self, node):
        """
        機能: 対応表に登録した変数参照を置換する。
        引数: node(ast.Name)。
        返り値: ast.AST の置換済み参照。
        """
        if node.id in self.mapping:
            result = ast.parse(self.mapping[node.id], mode='eval').body
            if hasattr(result, 'ctx'): result.ctx = node.ctx
            return ast.copy_location(result, node)
        return node


def statements(text):
    """
    機能: 記述した接続処理を構文木へ変換する。
    引数: text(str)。
    返り値: list[ast.stmt]。
    """
    return ast.parse(text).body


def component(function, prefix):
    """
    機能: 影再生の初期化・一行更新・結果を独立変数へ分解する。
    引数: function(ast.FunctionDef)、prefix(str)。
    返り値: tuple[list,list,ast.expr]。
    """
    item = copy.deepcopy(function)
    local = {x.id for x in ast.walk(item) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)}
    mapping = {name: prefix+name for name in local if name not in ('i', 'n')}
    mapping.update(atr='atr', trail_atr='atr', context='state', width_mode='0',
                   par=prefix+'par', prepare_allow=prefix+'allow',
                   raw_bad='signal_bad', raw_source='signal_source', raw_valid='signal_valid',
                   dynamic='dynamic' if prefix=='xs_' else 'False',
                   rounded='shadow_original.rounded', close_positions='shadow_original.close_positions',
                   inventory='shadow_original.inventory')
    item = Names(mapping).visit(item)
    loop = next(x for x in item.body if isinstance(x, ast.For))
    index = item.body.index(loop)
    pre = item.body[1:index]
    post = item.body[index+1:]
    return pre, loop.body, post


def build():
    """
    機能: 旧影と実会計を原本行順で接続した新モジュールを生成する。
    引数: なし。
    返り値: dict[str,str] の出力先。旧ファイルは変更しない。
    """
    text = shadow_source()
    (HERE / 'shadow_engine.py').write_text(text, encoding='utf-8')
    shadowfn = next(x for x in ast.parse(text).body if isinstance(x, ast.FunctionDef) and x.name=='simulate')
    ns_pre, ns_body, ns_post = component(shadowfn, 'ns_')
    xs_pre, xs_body, xs_post = component(shadowfn, 'xs_')
    actualtext = (ROOT / 'work/wave_v85/engine.py').read_text(encoding='utf-8')
    actualtext = replace_once(actualtext, 'last_exit+300.-1e-8', 'last_exit+cooldown_seconds-1e-8')
    actualtext = replace_once(actualtext, '元組開始で実の5分休止が終わっていません', '実全返済からの指定休止が終わっていません')
    fn = next(x for x in ast.parse(actualtext).body if isinstance(x, ast.FunctionDef) and x.name=='simulate')
    removed = {'plans','execution_plans','shadow_atr','bad','bad_source'}
    fn.args.args = [x for x in fn.args.args if x.arg not in removed]
    fn.args.defaults = []
    fn.args.args += [ast.arg(arg=x) for x in ('atr','state','tick','start','us_open','session_close','ns_par','xs_par','signal_bad','signal_source','signal_valid','dynamic','dynamic_activation','dynamic_width','cooldown_seconds')]
    loop = next(x for x in fn.body if isinstance(x, ast.For))
    index=fn.body.index(loop)
    actual_pre=fn.body[1:index]
    actual_body=loop.body
    actual_post=fn.body[index+1:]
    reset=[]
    for prefix in ('ns_','xs_'):
        reset += statements(f"""
if feedback_row>=0:
    if {prefix}d!=0 and {prefix}inv[0]+{prefix}inv[1]>.5:
        {prefix}oldtc={prefix}tc
        {prefix}tc,{prefix}gain,{prefix}done=shadow_original.close_positions({prefix}pos,{prefix}used,{prefix}trades,{prefix}tc,-1,100000,feedback_price,feedback_row,72,{prefix}campaign)
        {prefix}realized+={prefix}gain
        for {prefix}k in range({prefix}oldtc,{prefix}tc):
            if {prefix}oc>=len({prefix}orders): raise ValueError('影終了の記録上限です')
            {prefix}cash+={prefix}trades[{prefix}k,2]*{prefix}trades[{prefix}k,3]*feedback_price
            {prefix}orders[{prefix}oc,:]=np.array([feedback_row,feedback_row-1,{prefix}campaign,-{prefix}trades[{prefix}k,2],{prefix}trades[{prefix}k,3],feedback_price,72.,0.])
            {prefix}oc+=1
        {prefix}inv=shadow_original.inventory({prefix}pos,{prefix}used)
        if {prefix}cc>=len({prefix}cycles): raise ValueError('影組の記録上限です')
        {prefix}cycles[{prefix}cc,:]=np.array([{prefix}campaign,{prefix}entry_row,feedback_row,{prefix}realized-{prefix}base,{prefix}risk,{prefix}a,{prefix}cycle_gross,{prefix}cycle_net,{prefix}d,72.])
        {prefix}cc+=1
    {prefix}d=0
    {prefix}pending_d=0
    {prefix}pending_action=0
    {prefix}pending_prepare_row=-1
    {prefix}pending_prepare_id=-1
    {prefix}pending_until=0.
    {prefix}pending_row=-1
    {prefix}main_floor=np.nan
    {prefix}main_level=np.nan
    {prefix}stop_level=np.nan
    {prefix}split_level=np.nan
    {prefix}split_done=False
    {prefix}narrowed=False
    {prefix}peak=0.
    {prefix}last_exit=time[feedback_row]
    {prefix}neutral_since=-1.
""")
    # ----------------------------------------
    # 旧計画の破棄は現在行にのみ作用し、過去の plans を書き換えない。
    for body, prefix in ((ns_body,'ns_'),(xs_body,'xs_')):
        target=next(j for j,x in enumerate(body) if isinstance(x,ast.Assign) and any(isinstance(y,ast.Subscript) and isinstance(y.value,ast.Name) and y.value.id==prefix+'execution_plans' for y in x.targets))
        body[target:target]=statements(f'if feedback_row>=0: {prefix}effective[:]=np.nan')
    aliases=statements('\nplans=xs_plans\nexecution_plans=xs_execution_plans\nshadow_atr=xs_atr_curve\nbad=np.zeros(n,np.int8)\nbad_source=signal_source\nns_allow=np.zeros(n,np.bool_)\nxs_allow=np.zeros(n,np.bool_)\nfeedback_row=-1\nfeedback_price=0.\nreentry_events=np.zeros((12000,6))\nreentry_count=0\ngate_arm=-1\ngate_campaign=-1\ngate_entry=-1\ngate_mfe=np.zeros(n)\ngate_arm_rows=np.full(n,-1,np.int64)\ngate_armed=np.zeros(n,np.bool_)\ngate_eligible=np.zeros(n,np.bool_)\n')
    gate_code=statements('\nif ns_d==0:\n    gate_arm=-1;gate_campaign=-1;gate_entry=-1\nelif not np.isfinite(price[i]) or price[i]<=0:\n    pass\nelse:\n    if ns_campaign!=gate_campaign or ns_entry_row!=gate_entry:\n        gate_arm=-1;gate_campaign=ns_campaign;gate_entry=ns_entry_row\n    gate_mfe[i]=ns_d*(ns_extreme-ns_anchor)/ns_a\n    if gate_arm<0 and gate_mfe[i]>=1.5: gate_arm=i\n    gate_arm_rows[i]=gate_arm\n    gate_armed[i]=gate_arm>=0\n    if gate_arm>=0 and signal_source[i]>gate_arm:\n        bad[i]=signal_bad[i]\n        gate_eligible[i]=True\natr_curve[i,:]=xs_atr_curve[i,:]\n')
    before=statements("\nif feedback_row>=0:\n    if reentry_count>=len(reentry_events): raise ValueError('実返済時計証跡の保存上限です')\n    reentry_events[reentry_count,:]=np.array([feedback_row,i,time[feedback_row]+cooldown_seconds,campaign,ns_campaign,xs_campaign])\n    reentry_count+=1\nns_allow[i]=closed\n")
    # 通常影だけが新規準備の可否を決め、出口影は同じ新規準備行だけを使う。
    middle=statements('xs_allow[i]=ns_prepare_count>0 and ns_prepare_events[ns_prepare_count-1,1]==i')
    after=statements('\nfeedback_row=-1\nif closed_now:\n    feedback_row=i\n    feedback_price=fill\n')
    ns_step=ast.For(target=ast.Name(id='ns_once',ctx=ast.Store()),iter=ast.parse('range(1)',mode='eval').body,body=ns_body,orelse=[])
    xs_step=ast.For(target=ast.Name(id='xs_once',ctx=ast.Store()),iter=ast.parse('range(1)',mode='eval').body,body=xs_body,orelse=[])
    invalid_reset=statements("if feedback_row>=0 and (not np.isfinite(price[i]) or price[i]<=0):\n    ns_plans[i,:]=np.nan\n    xs_plans[i,:]=np.nan")
    clear_feedback=statements('feedback_row=-1')
    loop.body=before+reset+[ns_step]+middle+[xs_step]+invalid_reset+gate_code+clear_feedback+actual_body+after
    extra=ast.parse('(ns_plans,ns_execution_plans,ns_prepare_events[:ns_prepare_count],ns_entry_preparations[:ns_entry_prepare_count],xs_plans,xs_execution_plans,xs_prepare_events[:xs_prepare_count],xs_entry_preparations[:xs_entry_prepare_count],xs_dynamic_events[:xs_dynamic_count],reentry_events[:reentry_count],gate_mfe,gate_arm_rows,gate_armed,gate_eligible)',mode='eval').body
    ret=actual_post[-1]
    ret.value=ast.Tuple(elts=list(ret.value.elts)+list(extra.elts),ctx=ast.Load())
    fn.body[0]=ast.Expr(value=ast.Constant(value='''機能: 通常影、改修出口影、実玉を同じ保存観測の順で更新する。

    引数: time/price/atr/state と公開根拠・静観配列(ndarray)、両影設定(ns_par/xs_par:ndarray)、
    数量・方針(int)、閾値・実返済後休止(float)、約定モデル・詳細(bool)。
    返り値: 旧実玉18配列と両影計画・準備・幅短縮・実返済時計・半減根拠(tuple[ndarray,...])。
    現在行で作った条件は次の原本行以降へ適用し、実全返済の次行から両影を再準備する。
    通常影のMFEを途中半減へ使い、EMA・ATR・B00の過去情報を消さない。'''))
    fn.body=[fn.body[0]]+statements('n=len(price)')+ns_pre+xs_pre+aliases+actual_pre+[loop]+actual_post
    header='"""通常影・改修出口影・実玉を同一原本行で更新する生成済み再生器。"""\nfrom __future__ import annotations\nimport numpy as np\nfrom numba import njit\nfrom wave85_engine import close_slots, shadow_engine, FIELDS\nimport wave86_shadow as shadow_original\n'
    module=ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))
    rendered=ast.unparse(module)
    for anchor,label in [('        for ns_once in range(1):','通常影の更新。元の半減根拠となる価格進捗を保つ。'),
                         ('        for xs_once in range(1):','改修出口影の更新。通常影の新準備行だけ開始する。'),
                         ('        if ns_d == 0:','通常影の1.5ATR到達後に新しく公開されたB00だけ半減へ渡す。'),
                         ('        if used + 1 >= len(pos)','実玉の独立約定・枠会計。現在行で作った線は使わない。')]:
        if anchor in rendered:
            rendered=rendered.replace(anchor,'        # ----------------------------------------\n        # '+label+'\n'+anchor,1)
    (HERE/'engine.py').write_text(header+rendered+'\n',encoding='utf-8')
    return dict(shadow=str(HERE/'shadow_engine.py'),actual=str(HERE/'engine.py'))


if __name__ == '__main__':
    print(build())

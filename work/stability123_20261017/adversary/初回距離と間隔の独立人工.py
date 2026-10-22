"""実市場を読まず、初回距離と間隔だけの変更を人工価格で反証する。"""

import ast
from decimal import Decimal, ROUND_FLOOR
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
import engine123 as ENGINE
import catalog123 as CATALOG

CHECKS = []


def sha(path: Path) -> str:
    """
    機能: 小SOURCEから指紋を作る。
    引数: path(Path)はSOURCE。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, name: str):
    """
    機能: 保存済みSOURCEを私有名で読み込む。
    引数: path(Path)、name(str)。
    返り値: moduleは人工専用の比較先。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(ok, label: str) -> None:
    """
    機能: 独立期待の合否を記録する。
    引数: ok(bool)、label(str)。
    返り値: None。
    """
    assert bool(ok), label
    CHECKS.append(label)


def fixture(last, times=None, bid=None, ask=None) -> tuple:
    """
    機能: 完全人工の五列とTOPIX一枚料の設定を組み立てる。
    引数: last/times/bid/ask(数値配列またはNone)。
    返り値: tuple[dict,dict]は気配と時間・数量・費用設定。
    """
    x = np.asarray(last, dtype=float)
    b = x if bid is None else np.asarray(bid, dtype=float)
    a = b+.5 if ask is None else np.asarray(ask, dtype=float)
    t = np.arange(len(x), dtype=float) if times is None else np.asarray(times, dtype=float)
    return (dict(row=np.arange(len(x),dtype=np.int64),time=t,last=x,bid=b,ask=a),
            dict(cap=10,multiplier=1000.,fee=41.8,observed_tick=.5,
                 session_start=0.,entry_end=400.,close_time=500.,session_end=900.))


def account(output: tuple, q: dict, s: dict) -> None:
    """
    機能: 一枚実新規と代理返済の全UIDを独立の料金算式で照合する。
    引数: output(tuple)、q/s(dict)。
    返り値: None。代理を通常返済注文へ混ぜないことも確認する。
    """
    o,l,c,n,p,context = output
    fee = int(Decimal(str(s['fee'])).to_integral_value(rounding=ROUND_FLOOR))
    check(len(l)==0 and np.all(o[:,1]==1), '途中返済なし・通常引けfill偽造なし')
    check(context['measured'] and len(o)==len(p), '代理全UID一対一')
    check(len(set(o[:,0]))==len(o), '新規UID重複なし')
    i = int(np.flatnonzero(q['row']==context['reference_row'])[0])
    expected = []
    for entry, proxy in zip(o,p):
        xp = q['bid'][i] if entry[2]==1 else q['ask'][i]
        net = entry[2]*(xp-entry[7])*s['multiplier']-2*fee
        expected.append(net)
        check(proxy[0]==entry[0] and proxy[6]==entry[7] and proxy[9]==xp
              and proxy[11]==2*fee and proxy[12]==net, '元建値・返済BBO・料金floorと純損益')
        check(entry[4]>entry[3], '新規判断と実fillは別原行')
    check(n['net']==n['cash']==sum(expected), '全玉純損益と現金の独立和')
    check(n['profit']==sum(max(x,0.) for x in expected)
          and n['loss']==sum(max(-x,0.) for x in expected), '利益と損失を相殺前に集計')
    check(n['fees']==2*fee*len(o) and n['unclosed']==0, '全注文料・代理後未返済ゼロ')
    check(context['reference_time']==600. and context['scheduled_time']==900.,
          '参照気配時刻と予定引けの分離')


def main() -> dict:
    """
    機能: 十九仕様の真の発火線と最小差分・旧基準・価格保護を独立に確認する。
    引数: なし。
    返り値: dictはSOURCEと人工だけの検査証跡。
    """
    files = [BASE/'core123.py', BASE/'engine123.py', BASE/'catalog123.py']
    sources = {str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in files}
    core_source = (BASE/'core123.py').read_text(encoding='utf-8')
    replay = next(node for node in ast.parse(core_source).body
                  if isinstance(node,ast.FunctionDef) and node.name=='replay')
    check(not any(isinstance(node,ast.Name) and isinstance(node.ctx,ast.Store)
                  and node.id=='initial' for node in ast.walk(replay)),
          '初回距離initialを建玉評価ローカルで上書きしない')
    specs = CATALOG.specifications()
    expected = {(3.,float(g)) for g in (1,2,3,4,5,6,8,10,12,15)}
    expected |= {(float(g),float(g)) for g in (1,2,3,4,5,6,8,10,12,15)}
    check(len(specs)==19 and {(x['initial'],x['spacing']) for x in specs}==expected,
          '二系統十九uniqueと3/3一つだけの統合')
    check(sum(x['reused'] for x in specs)==1 and next(x for x in specs if x['reused'])['id']=='I3_G3',
          '旧保存基準一つと新十八を別計数')
    examples = []
    accounts = 0
    for spec in specs:
        initial,gap = spec['initial'],spec['spacing']
        path = [4000.,4000.+initial,4000.+initial,4000.+initial+gap,4000.+initial+gap,
                4000.+initial+gap]
        q,s = fixture(path,times=[0,1,2,3,4,600])
        out = ENGINE.evaluate(q,s,'CLOSE_PROXY',initial,gap)
        buy = out[0][out[0][:,2]==1]
        check(len(buy)==2 and len(out[0])==2, '二段人工で初回一枚制限と後段一枚のみ')
        check(np.array_equal(buy[:,3],[1,3]) and np.array_equal(buy[:,4],[2,4]),
              '初回と二段目の判断・次正常行fill')
        check(np.array_equal(buy[:,17],[4000.+initial,4000.+initial+gap]),
              '初回fill後も距離引数を維持した実発火線')
        account(out,q,s)
        mirrored = {key:value.copy() for key,value in q.items()}
        mirrored['last']=8000.-q['last']
        mirrored['bid']=8000.-q['ask']
        mirrored['ask']=8000.-q['bid']
        sell = ENGINE.evaluate(mirrored,s,'CLOSE_PROXY',initial,gap)
        check(np.array_equal(out[0][:,[3,4,10]],sell[0][:,[3,4,10]])
              and np.array_equal(8000.-out[0][:,17],sell[0][:,17]), '売鏡像の判断原行と発火線')
        check(out[3]['net']==sell[3]['net'] and out[3]['fees']==sell[3]['fees'],
              '上下鏡像の費用と純損益')
        examples.append(dict(id=spec['id'],first_line=float(buy[0,17]),second_line=float(buy[1,17])))
        accounts += 2

    # ----------------------------------------
    # 旧3/3基準は六配列・二辞書を含む返却物全体が同一。
    old = load(ROOT/'work/stability122_20261017/engine122.py','adversary_old_terminal122')
    q,s = fixture([4000,4003,4003,4006,4006,4012,4012,4006,4006,4000,4000,4000,4000],
                   times=list(range(11))+[600,601])
    for kind in ('EARLY','CLOSE_PROXY'):
        current = ENGINE.evaluate(q,s,kind,3.,3.)
        previous = old.evaluate(q,s,kind)
        check(all(np.array_equal(a,b,equal_nan=True) if isinstance(a,np.ndarray) else a==b
                  for a,b in zip(current,previous)), '旧122の3/3全返却物exact一致')
        accounts += 1

    # ----------------------------------------
    # 新安値後の待機極値だけ追従し、既存玉の建値は変えない。
    q,s = fixture([4000,4003,4003,3980,3980,3986,3986,3986],
                   times=[0,1,2,3,4,5,6,600])
    out = ENGINE.evaluate(q,s,'CLOSE_PROXY',3.,3.)
    buy = out[0][out[0][:,2]==1]
    check(np.array_equal(buy[:2,17],[4003.,3986.]), '新安値3980から次段3986へ追従')
    check(out[4][out[4][:,0]==1][0,6]==4003.5, '新安値や後続追加で旧建値4003.5を変えない')
    account(out,q,s)
    accounts += 1

    # ----------------------------------------
    # 間隔15ptでも気配幅は1pt固定。不利fill許容も一刻みのまま。
    q,s = fixture([4000,4015,4015,4030,4030,4030],times=[0,1,2,3,4,600])
    q['ask']=q['bid']+2.
    wide = ENGINE.evaluate(q,s,'CLOSE_PROXY',15.,15.)
    check(len(wide[0])==0 and wide[3]['net']==0 and wide[3]['wins']==0,
          '大間隔でもspread二ptの新規を許容しない・無取引勝ちなし')
    q,s = fixture([4000,4003,4003,4003],times=[0,1,2,600],bid=[4000,4003,4004,4004])
    slipped = ENGINE.evaluate(q,s,'CLOSE_PROXY',3.,15.)
    check(len(slipped[0])==0 and slipped[3]['canceled']==1,
          '初回も後段も最初次quoteの不利0.5pt超は取消')
    accounts += 2

    # ----------------------------------------
    # 旧Falseの再現は人工だけ。通常/JIT同値では防げない変数衝突を記録する。
    badpath = BASE/'金融前の引数と既存局所変数の衝突/core123.py'
    bad = load(badpath,'adversary_archived_initial_collision123')
    q,s = fixture([4000,4003,4003,4006,4006,4006],times=[0,1,2,3,4,600])
    args = [q[key] for key in ('row','time','last','bid','ask')]
    cfg = dict(s,unit=1.,initial=3.,mode=2,trail=float('inf'),spacing=3.,reset_after_profit=False)
    cfg['close_time']=float('inf')
    failed = bad.replay.py_func(*args,**cfg)
    corrected = ENGINE.BASE.replay(*args,**cfg)
    check(len(failed[0])==10 and len(corrected[0])==2, '旧衝突反例は十枚発火・修正版は期待二枚')
    reproduction = dict(passed=False, intentional_counterexample=True,
                        archived_core_sha256=sha(badpath), expected_entries=2,
                        actual_archived_entries=len(failed[0]), corrected_entries=len(corrected[0]),
                        原因='引数initialが初回fillの手数料後評価で上書きされ、以後の段階線に負の円評価を使った。',
                        金融再生=0, 原市場読取=0, API=0)
    (HERE/'金融前の旧initial衝突を人工だけで再現.json').write_text(
        json.dumps(reproduction,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    check(sources=={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in files},
          '最終三SOURCE開始終端不変')
    return dict(passed=True,engine_sha256=sha(BASE/'engine123.py'),
                core_sha256=sha(BASE/'core123.py'),source_SHA256=sources,
                inspections=len(CHECKS),checks=CHECKS,synthetic_accounts=accounts,
                expected_first_two_lines=examples,
                比較='同じモデルの通常/JIT一致だけに頼らず、初回と次段を外部で計算した。旧衝突は金融前に保存・訂正。',
                原市場読取=0, 実NPZ追加読取=0, 金融再生=0, API=0, 台帳変更=0)


if __name__=='__main__':
    destination=HERE/'初回と間隔の独立発火線及び旧基準同値.json'
    assert not destination.exists()
    try:
        result=main()
    except Exception as exc:
        (HERE/'独立人工False.json').write_text(json.dumps(
            dict(passed=False,error=repr(exc),checks=CHECKS),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,engine_sha256=result['engine_sha256'],
                          core_sha256=result['core_sha256'],inspections=result['inspections'],
                          synthetic_accounts=result['synthetic_accounts'],proof_sha256=sha(destination)),ensure_ascii=False))

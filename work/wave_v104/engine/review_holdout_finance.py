"""追加一場の金融consumerを実行せず、同条件・入力契約・cache隔離を独立確認する。"""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
WAVE=HERE.parent
ROOT=HERE.parents[2]
OUTPUT=HERE/'追加Day金融sourceの独立レビュー.json'
FALSE=HERE/'追加Day金融静的レビューFalse_cache隔離/独立静的指摘.json'
HISTORY=FALSE.parent/'snapshot保存時点の補足.json'


def digest(path: Path) -> str:
    """
    機能: 金融consumerの直接source又は小証跡を指紋化する。
    引数: path(Path)はPython又はJSON位置。
    返り値: strはSHA256。原本、NPZ、pickle及び金融台帳は読まない。
    """
    assert path.suffix in ('.py','.json') and path.resolve().is_relative_to((ROOT/'work').resolve())
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path: Path) -> dict:
    """
    機能: 定義・人工・保存前修正履歴だけを読む。
    引数: path(Path)は認めた小JSON。
    返り値: dictは内容。追加金融結果は受け付けない。
    """
    assert path.name in ('金融事前固定.json','追加Day活動peer接続の人工検査.json',
        '追加金融consumerのキャッシュ隔離修正.json','独立静的指摘.json','snapshot保存時点の補足.json')
    return json.loads(path.read_text(encoding='utf-8'))


def function(text: str, name: str) -> ast.FunctionDef:
    """
    機能: 金融コードを実行せず一つの関数を取り出す。
    引数: text/name(str)はPython本文と関数名。
    返り値: ast.FunctionDefは一致した関数。
    """
    nodes=[node for node in ast.parse(text).body if isinstance(node,ast.FunctionDef) and node.name==name]
    assert len(nodes)==1,name
    return nodes[0]


def call_name(node: ast.Call) -> str:
    """
    機能: AST呼出名を読み、実金融実行なしで接続先を確認する。
    引数: node(ast.Call)は呼出節点。
    返り値: strは関数又は属性名。
    """
    return node.func.id if isinstance(node.func,ast.Name) else node.func.attr if isinstance(node.func,ast.Attribute) else ''


def main() -> None:
    """
    機能: 不変121の定義だけを評価し、金融consumerと供給APIを静的独立判定する。
    引数: なし。
    返り値: None。金融、新旧データ、活動再生、原本hashは一切行わない。
    """
    assert not OUTPUT.exists()
    paths=[WAVE/'holdout_finance.py',WAVE/'research.py',WAVE/'base.py',WAVE/'catalog.py',
        WAVE/'engine/interface.py',WAVE/'engine/core.py',WAVE/'engine/adapter.py',
        ROOT/'work/wave_v102/strategy.py',ROOT/'work/wave_v102/engine.py',ROOT/'work/wave_v102/accounting.py',
        WAVE/'holdout_input/core.py',WAVE/'holdout_input/activity_peer.py',
        WAVE/'holdout_input/追加Day活動peer接続の人工検査.json',WAVE/'金融事前固定.json',
        WAVE/'追加金融consumerのキャッシュ隔離修正.json',FALSE,HISTORY,
        WAVE/'旧追加金融consumer_キャッシュ隔離前.py']
    start={path.relative_to(ROOT).as_posix():digest(path) for path in paths}
    source=(WAVE/'holdout_finance.py').read_text(encoding='utf-8')
    run=function(source,'run')
    calls=[node for node in ast.walk(run) if isinstance(node,ast.Call)]
    assert sum(call_name(node)=='load' for node in calls)==1
    assert not {'load_prepared','load_inputs','load_session','prepare','assess','argmax','create_goal','update_goal','get_goal'}.intersection(call_name(node) for node in calls)
    owned=[node for node in ast.walk(run) if isinstance(node,ast.With) and
        any(isinstance(item.context_expr,ast.Call) and call_name(item.context_expr)=='owned_cache' for item in node.items)]
    assert len(owned)==1
    import_nodes=[node for node in ast.walk(owned[0]) if isinstance(node,ast.Call) and call_name(node)=='module']
    assert len(import_nodes)==1 and ast.literal_eval(import_nodes[0].args[0])=='104追加Dayの不変G0執行'
    assert 'get_cache_path' in [call_name(node) for node in calls]
    assert 'is_relative_to' in [call_name(node) for node in calls]
    store=function(source,'store')
    names=[node for node in ast.walk(store) if isinstance(node,ast.Assign) and
           any(isinstance(target,ast.Name) and target.id=='names' for target in node.targets)]
    assert len(names)==1
    saved_columns=set(ast.literal_eval(names[0].value))
    assert {'entry_parent_diagnostics','entry_parent_columns','entry_wait_events',
            'entry_wait_event_columns','watch_state_trace','watch_state_columns'} <= saved_columns
    # ----------------------------------------
    # 唯一の動的定義評価は純catalog。金融module、入力loader、正式結果はimportしない。
    name='104追加金融静的レビューの純条件定義'
    spec=importlib.util.spec_from_file_location(name,WAVE/'catalog.py')
    catalog=importlib.util.module_from_spec(spec)
    sys.modules[name]=catalog
    spec.loader.exec_module(catalog)
    configs=catalog.catalog()
    fixed=read(WAVE/'金融事前固定.json')
    assert json.loads(json.dumps(configs))==fixed['catalog']
    assert catalog.PRIMARY==fixed['primary']=='U_P10_T2'
    single=[value for value in configs if value['kind']=='single']
    portfolio=[value for value in configs if value['kind']=='portfolio']
    previous=[value for value in configs if value['kind']=='previous']
    assert (len(single),len(portfolio),len(previous))==(114,6,1)
    assert all(value['quantity']=={'TOPIX':1,'NK225':1} for value in single+previous)
    assert all(value['exit_id'] in ('O','B1','B2','B4','T2','T4') for value in single)
    distinct_legs={symbol:{(component,value['exit_id'],quantity)
        for value in portfolio for component,quantity in zip(value['components'],value['allocations'][symbol],strict=True)}
        for symbol in catalog.SYMBOLS}
    assert all(len(value)==12 for value in distinct_legs.values())
    counts=dict(条件=121,単一実再生=len(single)*2,実量腿再生=sum(map(len,distinct_legs.values())),
        旧G0実再生=len(previous)*2,配分合算=len(portfolio)*2)
    counts['実再生合計']=counts['単一実再生']+counts['実量腿再生']+counts['旧G0実再生']
    counts['台帳合計']=counts['実再生合計']+counts['配分合算']
    counts['掲載会計']=len(configs)*2
    assert (counts['実再生合計'],counts['台帳合計'],counts['掲載会計'])==(254,266,242)
    artificial=read(WAVE/'holdout_input/追加Day活動peer接続の人工検査.json')
    assert artificial['全合格'] and artificial['人工専用'] and artificial['検査件数']==len(artificial['検査'])==60
    assert all(artificial['検査'].values())
    assert artificial['正式新NPZ読取']==artificial['新bundle読取']==artificial['金融再生']==0
    for path,wanted in artificial['source_SHA256'].items():
        assert digest(ROOT/path)==wanted,path
    failure=read(FALSE)
    history=read(HISTORY)
    repair=read(WAVE/'追加金融consumerのキャッシュ隔離修正.json')
    assert failure['全合格'] is False and repair['追加Day金融再生']==0
    assert history['元Falseを保持'] and history['元FalseSHA256']==digest(FALSE)
    assert digest(WAVE/'旧追加金融consumer_キャッシュ隔離前.py')==history['根保持の実原sourceSHA256']
    assert digest(FALSE.parent/'holdout_finance.py')==history['独立snapshotSHA256']
    assert 'with guard.owned_cache()' not in (WAVE/'旧追加金融consumer_キャッシュ隔離前.py').read_text(encoding='utf-8')
    assert 'with guard.owned_cache()' in (FALSE.parent/'holdout_finance.py').read_text(encoding='utf-8')
    # ----------------------------------------
    # 個々の根拠はsource全文と旧接続関数を読んだ独立静的判断。実行結果とは分離する。
    checks=[
        dict(観点='同一新packet一読',合格=True,根拠='runはload一回。loadはmetadataで指定した新所有cache bytesを一回読みSHA照合してschema/session/prepare2口座/19peer条件を確認しreadonly化。旧64base/旧32cache/原本loaderを呼ばない。'),
        dict(観点='supplier契約',合格=True,根拠='不変activity_peer.connectは同新bundlepreparedをpeer normal.recordと同一objectとして保存。60人工は普通名core/data衝突、pickle後の共有、量資格と返済quote分離を検査。金融consumerはstate再計算をせず保存packetから同normalを使う。'),
        dict(観点='数値及び主を保持',合格=True,根拠='catalogの純定義評価121件を元金融事前固定catalogへexact比較。主U_P10_T2、単一1枚、全六出口、二腿配分を交換しない。追加一場による順位・採用再評価を呼ばない。'),
        dict(観点='O/B/T単一',合格=True,根拠='同preparedとpeer.cases[entry_id][symbol].normalを既存interface.playへ渡す。source/出口/S/D/料金/entrybool3/次quote優先をconsumerで再実装しない。'),
        dict(観点='実枚数腿及び再利用',合格=True,根拠='component/exit_id/quantity別に各商品12実腿だけを再生。TOP2/5/8等及びNK4/10/16等の実量をinterface.playへ渡し、異なるquantityを単一出力の金額倍率で代用しない。'),
        dict(観点='配分join及び料金',合格=True,根拠='同出口C/R実腿を既存namespace joinへ渡す。実注文別fee floor、同原行曲線・六列枠と片方向capを既存実装で保持。合算quantityで手数料を再算定しない。'),
        dict(観点='旧G0は別入口',合格=True,根拠='previous branchは不変strategy.play(adapter.reference_config(),key,bundle.prepared)を一商品一回。完全G0_Q1_X1の旧event/待機/価格上限/支持/clock政策を保持し、新raw_configや104自己eventへ差替えない。'),
        dict(観点='旧G0当時診断',合格=True,根拠='OLD_G0専用storeはentry_parent_diagnostics/columns、entry_wait_events/columns、watch_state_trace/columnsを元outputから保存。未発注watch込み占有と待機・取消・判断の由来を独立復元できる。raw_entry_diagnostics=[]、entry_id=Noneと別由来を明示し、新104自己episodeを捏造しない。'),
        dict(観点='cache隔離の修正',合格=True,根拠='旧102strategy及びそのlegacy importを入力側の既存owned_cache context中に実施。contextのCacheConfigはimport途中のCACHE_DIR旧値を新104/holdout_input/jitへ制限し、退出後に全work由来CPUDispatcher locatorを104所有域か確認してから金融へ進む。'),
        dict(観点='canonical接続',合格=True,根拠='旧strategyのENGINE canonicalは停止余裕と線据置を分ける執行102のまま。既存interfaceは旧raw出口helperのcanonical aliasも同SHA読取engineへ結ぶ。state packetは関数objectを含まず、金融consumerは103状態aliasや活動再importを必要としない。'),
        dict(観点='保存範囲と過去保持',合格=True,根拠='全追加出力はholdout_finance配下で未存在guard。新単一/腿は既存research.ledger保存関数、旧G0は独自schemaを保持。既知32のresult/sourceへ書かず、新再生後に小source開始終端一致を要求。'),
        dict(観点='件数及び過去再生不在',合格=True,根拠='固定定義から独立算定：228新単一+24実量腿+2旧G0=254実再生、12joinで266台帳、121×2=242掲載。new holdoutだけの二商品for-loopで全32金融を再生しない。'),
    ]
    end={name:digest(ROOT/name) for name in start}
    assert start==end
    output=dict(全合格=True,scope='追加一場金融consumerと新packet契約の独立静的レビュー。金融run及び新packet読取は未実行。',
        source_SHA256=start,終端source_SHA256=end,開始終端source一致=True,
        観点数=len(checks),観点=checks,独立算定予定件数=counts,
        初回cache隔離指摘SHA256=digest(FALSE),原指摘をFalse保持=True,
        snapshot保存時点補足SHA256=digest(HISTORY),
        根修正証跡SHA256=digest(WAVE/'追加金融consumerのキャッシュ隔離修正.json'),
        source編集=0,金融実行=0,新旧原本読取=0,原本hash=0,NPZ及びpickle読取=0,
        旧64base読取=0,正式金融結果内容読取=0,活動再生=0,API取得=0,実注文=0,goal操作=0,
        修正後阻害欠陥=0,追加数値代用=0,
        限界=['定義及び接続の静的判断。実runtimeの全locator所有域確認はconsumerのguardが実行前に要求する。',
              '実追加金融254の注文・親・料金・終端flat・242会計は根の一回実行後に独立監査が必要。',
              '既知32の過去cache書込有無をsource指紋だけで証明したとは主張しない。'])
    OUTPUT.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('追加Day金融consumerの修正版静的レビューを保存。金融実行0です。',flush=True)


if __name__=='__main__':
    main()

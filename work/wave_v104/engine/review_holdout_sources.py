"""追加Day本文を読まず、入力sourceと人工証跡を独立に静的確認する。"""

import ast
import hashlib
import json
from pathlib import Path
import sys


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
INPUT = HERE.parent/'holdout_input'
OUTPUT = HERE/'追加Day入力sourceの独立レビュー.json'
EXPECTED = {
    'core.py': 'f8de55e706e3bc97b41f833ff7a9e0649b8e71532429f86748b57ada9aaa1485',
    'data.py': '6ad31013173eb9a7e3d189d89eac1fdb0b8436bc664c35840668da9bc1a9a54b',
    'prepare.py': '4c5125c6c2392a795d17ca8041e6628c09220f5f7df3c19f9e7c74ea84667019',
    'artificial.py': '59dbedf7a3545babbcc348efd5becab48ca59fe388940052d83344361a6e8594',
    '旧normal独立LPと完全prepareの人工検査.json': '0be5339c3ff6c737ee6ffecebd24c7dc055d698551aeaf0b543158995857f9b0',
    '入力schema.json': 'b67a0f1afaf78fd063ac56722161df7264aca41768a781c166d6f4fb865ceec6',
}


def digest(path: Path) -> str:
    """
    機能: source、schema及び小証跡だけを指紋化する。
    引数: path(Path)は読取対象。
    返り値: strはSHA256。book、npz、pickle及び金融出力は受け付けない。
    """
    assert path.suffix in ('.py','.json','.md')
    assert path.resolve().is_relative_to((ROOT/'work').resolve())
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path: Path) -> dict:
    """
    機能: 今回未読入力の計画・schema・人工証跡だけを読む。
    引数: path(Path)は限定JSON。
    返り値: dictは保存資料。新Dayの値及び金融結果は読まない。
    """
    assert path.parent.resolve() == INPUT.resolve()
    assert path.name in ('追加Day未読入力の固定計画.json','入力schema.json',
                         '旧normal独立LPと完全prepareの人工検査.json')
    return json.loads(path.read_text(encoding='utf-8'))


def function(source: str, name: str) -> ast.FunctionDef:
    """
    機能: 接続先の純関数をASTから読む。
    引数: source/name(str)はソース内容と関数名。
    返り値: ast.FunctionDefは一致する一つの関数。モジュールはimportしない。
    """
    nodes=[node for node in ast.walk(ast.parse(source)) if isinstance(node,ast.FunctionDef) and node.name == name]
    assert len(nodes) == 1,name
    return nodes[0]


def call_names(source: str) -> list[str]:
    """
    機能: 実行記述の関数名を静的に一覧化する。
    引数: source(str)はPython本文。
    返り値: list[str]は呼出名。実売買関数又はgoal操作の不在確認に使う。
    """
    result=[]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node,ast.Call):
            if isinstance(node.func,ast.Name):
                result.append(node.func.id)
            elif isinstance(node.func,ast.Attribute):
                result.append(node.func.attr)
    return result


def main() -> None:
    """
    機能: 最終4source、人工28項目、旧資格と完全prepare接続を静的判定して保存する。
    引数: なし。
    返り値: None。source編集・人工再実行・新Day原本読取を行わない。
    """
    assert not OUTPUT.exists()
    plan=read(INPUT/'追加Day未読入力の固定計画.json')
    proof=read(INPUT/'旧normal独立LPと完全prepareの人工検査.json')
    schema=read(INPUT/'入力schema.json')
    sources={name:(INPUT/name).read_text(encoding='utf-8') for name in EXPECTED if name.endswith('.py')}
    start={path.relative_to(ROOT).as_posix():digest(path) for path in [INPUT/name for name in EXPECTED]}
    for name,wanted in EXPECTED.items():
        assert digest(INPUT/name) == wanted,name
    assert proof['全合格'] and proof['人工専用'] and proof['検査件数'] == len(proof['検査']) == 28
    assert all(proof['検査'].values())
    assert proof['件数']['原行及び旧collector照合配列数'] == 354
    assert proof['件数']['完全旧prepare接頭照合配列数'] == 94
    for name,wanted in proof['コードSHA256'].items():
        assert digest(ROOT/name) == wanted,name
    for name,wanted in plan['小直接依存SHA256'].items():
        assert digest(ROOT/name) == wanted,name
    for key in ('正式追加原本読取','新Day価格閲覧','旧32原本再読取','旧32大型入力cache読取',
                '金融結果読取','金融再生','現在API取得','実注文','goal操作','前場参照読取'):
        assert proof[key] == 0,key
    assert plan['session'] == '2026-10-13_Day' and plan['条件数'] == 121 and plan['事前指定主'] == 'U_P10_T2'
    assert schema['version'] == 2 and len(schema['columns']) == 44
    assert schema['訂正']['不変列数'] == 42
    assert schema['訂正']['変更列'] == ['volume_delta_usable','volume_delta']
    # ----------------------------------------
    # source呼出とopen位置を独立に機械確認し、人の静的読取の根拠を結ぶ。
    forbidden={'execute','simulate','play','account','create_goal','update_goal','get_goal'}
    calls={name:call_names(text) for name,text in sources.items()}
    for name,names in calls.items():
        assert not forbidden.intersection(names),(name,forbidden.intersection(names))
    rows=function(sources['core.py'],'rows')
    opens=[node for node in ast.walk(rows) if isinstance(node,ast.Call)
           and isinstance(node.func,ast.Attribute) and node.func.attr == 'open']
    assert len(opens) == 1 and len(opens[0].args) == 1 and ast.literal_eval(opens[0].args[0]) == 'rb'
    fanout=function(sources['core.py'],'fanout')
    assert len([node for node in ast.walk(fanout) if isinstance(node,ast.For)]) == 1
    assert {'step'}.issubset(set(call_names(ast.unparse(fanout))))
    build=function(sources['core.py'],'build_material')
    assert 'prepare' in call_names(ast.unparse(build))
    old_files={
        '旧77normal':'work/wave_v77/inputs/prepare.py',
        '旧91正常quote':'work/wave_v91/inputs/prepare.py',
        '独立94LP':'work/wave_v94/inputs_r1/last_price.py',
        '始値当時資格':'work/wave_v74/inputs/prepare_refs.py',
        '103全原行資格':'work/wave_v103/input/core.py',
        '103v2訂正':'work/wave_v103/input_v2/correction.py',
        '完全102準備':'work/wave_v102/strategy.py',
    }
    old_sha={name:digest(ROOT/name) for name in old_files.values()}
    assert 'execute' not in call_names(ast.unparse(function((ROOT/old_files['完全102準備']).read_text(encoding='utf-8'),'prepare')))
    evidence=[
        dict(観点='旧77/91正常採否',合格=True,
             根拠='NormalCollector.stepは価格clock→場内→旧parse_snapshot→CurrentPriceの順と旧57状態更新を旧77から保持。finishは不変price_recordへ接続。',
             境界='price_valid/quote_validは価格/BBOから生成し、十段及び出来高のvalidを返済資格へ転用しない。旧77同様、非空の不正timestampと逆行は失敗して救済しない。'),
        dict(観点='独立LP',合格=True,
             根拠='LPCollectorは不変94number/clockだけを参照。保存順、欠測後bit4、場外後bit8、原seq断裂bit2、初回bit1を旧94抽出と同じ順で適用。',
             境界='最良板不正でもLPは保持し、LP不正をBBO中値へ補完しない。'),
        dict(観点='103v2二列訂正',合格=True,
             根拠='全原行extract_rowsの直後に不変correct_arraysを適用。直前price_reset_reason逆行bit8をusableから除き支持用deltaをNaNへする。他42列を訂正関数内でdtype/shape/value全照合。',
             境界='raw→normal二mapは訂正後に同原seqの全五列一致で別に生成。過去64の対応合格を新一場の対応へ流用しない。'),
        dict(観点='一回streamと一回hash',合格=True,
             根拠='extract_jsonl.rowsの唯一のrb openでenumerate/hasher.update/byte_count/JSON解釈を行い、fanoutが同一iteratorをnormal・LP・103へ分配。',
             境界='同じ一回readの前後size/mtime_nsと読取byte数を一致要求。統計だけでは取引所の完全受信までは証明しない。'),
        dict(観点='原行mapとreset',合格=True,
             根拠='103は場外・欠測・不正・同clock後続を含む全原行を保存。normalのseqをsearchsorted後にraw_seq/time/LP/bid/ask全一致確認。非対応rawは-1のまま。',
             境界='近傍未来正常行への救済なし。price/depth/lp/volumeの別resetは元103定義を保持。'),
        dict(観点='当時始値',合格=True,
             根拠='first_valid時点のOpeningPrice/Timeが場内かつ現在clock以下の場合だけ旧opening_refが採用。それ以外は最初観測LP。build_materialと102.prepareでknown_from_i==0を二重要求。',
             境界='probe.latestは終端確認用。後のOpeningPriceをref_openへ遡及適用しない。固定G0準備にref_prevを要求しない。'),
        dict(観点='完全旧prepare',合格=True,
             根拠='旧77grid/entries、旧75legacy候補、I0-I3の独立価格lane、旧95I3窓、raw_last_records及びexecution_lp_indexを揃え、G0_Q1_X1指定で不変102.strategy.prepareを実関数接続。',
             境界='簡易signalへ代用なし。人工の全material/信号50列ずつ及び94接頭配列照合がこの接続を裏付ける。'),
        dict(観点='金融実行不在',合格=True,
             根拠='4sourceのAST呼出にexecute/simulate/play/account/goal関数なし。旧経済部品をimportしても準備関数以外を呼ばない。',
             境界='入力準備の合格を収益合格とは呼ばない。追加一場の121金融は根の別指示が必要。'),
        dict(観点='limit到達とflatの前提',合格=True,
             根拠='formalはlatest正常LP clock>=record.limitとnormal time>=limitの行を要求。旧91の正常quote全真値と併せ場末timerの実quoteを確保する。',
             境界='入力側は保有を生成しないためflat自体を判定しない。正式金融での終端trace==0は金融監査の責任。'),
        dict(観点='新旧書込隔離',合格=True,
             根拠='save/npz/bundle/schema/人工証跡はholdout_inputへ限定。sys.dont_write_bytecode、owned_cacheのCACHE_DIR代理で旧モジュールのJIT保存要求も所有jitへ固定。',
             境界='人工は全CPUDispatcher locatorの所有域を確認。旧77book-open対照だけBytesIOへ差し替え、旧sourceは変更しない。'),
        dict(観点='段階guardとFalse保持',合格=True,
             根拠='事前registerとroot確認後formalを排他的CLIで分離。既存metadata/raw出力を拒否、正式開始終端でstat/source不変、例外は追加入力不合格の別JSONへ保存し自動再抽出false。',
             境界='このレビューは正式抽出を開始しない。部分出力が残ればformalの未存在guardが再抽出を拒否する。'),
        dict(観点='消費APIとschema',合格=True,
             根拠='data.load_accountは44列dtype/shapeを照合しreadonlyで返す。load_bundleの一回bytes指紋からload_inputs/load_preparedを派生。元32へ混ぜず新一場だけを返す。',
             境界='verify=Trueは小直接sourceと新出力を検査し、原本を再hashしない。'),
    ]
    end={name:digest(ROOT/name) for name in start}
    assert start == end and all(digest(ROOT/name) == wanted for name,wanted in old_sha.items())
    output=dict(全合格=True,scope='追加Day入力の最終4sourceと旧純関数・人工証跡を静的独立読取したレビュー。正式原本内容及び金融は未読。',
        session=plan['session'],source編集=0,人工再実行=0,独立実データ実行=0,
        静的観点数=len(evidence),観点=evidence,人工証跡検査件数=28,
        人工証跡の旧collector照合配列数=354,人工証跡の完全prepare接頭配列数=94,
        source_SHA256=start,終端source_SHA256=end,旧直接純関数SHA256=old_sha,
        事前計画SHA256=digest(INPUT/'追加Day未読入力の固定計画.json'),
        人工SHA256=digest(INPUT/'旧normal独立LPと完全prepareの人工検査.json'),
        review_source_SHA256=digest(Path(__file__)),開始終端source一致=True,
        形式補正要求=0,阻害欠陥=0,新Day価格及び板値閲覧=0,原本行読取=0,原本hash=0,
        新旧NPZ及び大型cache読取=0,金融結果読取=0,金融再生=0,現在API取得=0,実注文=0,goal操作=0,
        限界=['人工28項目の実行は入力担当によるもの。独立側はsourceとその証跡の範囲及び現SHAを検討した。',
              '新場の一回抽出・原本五列対応・時刻完結は正式抽出終端後に別確認が必要。',
              '価格代理時計の因果を扱う。実受信時計、真の約定/取消、同主体補充は同定しない。'])
    OUTPUT.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('追加Day入力sourceの独立静的レビューを保存。原本内容・金融は未読です。',flush=True)


if __name__ == '__main__':
    main()

"""旧独立人工を保持し、最終入口準備と採用条件の静的確認を一件へ結ぶ。"""

import ast
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROJECT = ROOT.parents[1]


def sha(path: Path) -> str:
    """
    機能: 小さい直接sourceと完成証跡だけの内容指紋を求める。
    引数: path(Path)は対象ファイル。
    返り値: strはSHA256。原本や全台帳は読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 定義又は既人工のJSONを読む。
    引数: path(Path)は小さい定義又は人工証跡。
    返り値: dictは読取内容。正式金融結果は読まない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def function(path: Path, name: str) -> ast.FunctionDef:
    """
    機能: 指定名の関数を静的構文から取り出す。
    引数: path(Path)、name(str)は対象sourceと関数名。
    返り値: ast.FunctionDefは関数構文。対象の処理は実行しない。
    """
    found = [node for node in ast.parse(path.read_text(encoding='utf-8')).body
             if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(found) == 1
    return found[0]


def called(node: ast.AST) -> set[str]:
    """
    機能: 呼出の末尾名を抽出し、金融とNPZ経路を静的に確認する。
    引数: node(ast.AST)は関数構文。
    返り値: set[str]は呼出名。外部sourceは別に静的確認済みとする。
    """
    names = set()
    for current in ast.walk(node):
        if isinstance(current, ast.Call):
            if isinstance(current.func, ast.Attribute):
                names.add(current.func.attr)
            elif isinstance(current.func, ast.Name):
                names.add(current.func.id)
    return names


# ----------------------------------------


def main() -> None:
    """
    機能: 最終sourceと旧独立証跡及び純採用判定を、別の追記証跡へ接続する。
    引数: なし。
    返り値: None。正式32再準備、金融、原本、API、goalは実行しない。
    """
    target = HERE/'正式準備と最終sourceの独立確認.json'
    assert not target.exists()
    current = [ROOT/name for name in ('base.py', 'prepare.py', 'prepared_data.py', 'catalog.py', 'research.py',
        '数値設計案.json', '安定性の採用基準補足.json', 'peer/core.py', 'peer/api.py', 'peer/prices.py',
        'engine/core.py', 'engine/interface.py', 'engine/adapter.py', 'engine/old_finance_snapshot.py',
        'evaluation/assessment.py', 'evaluation/安定性採用判定の人工検査.json',
        'engine/19入口normalとO及び支持出口の結合人工.json')]
    current.append(Path(__file__))
    before = {str(path.relative_to(PROJECT)): sha(path) for path in current}
    former = read(HERE/'入口準備と最終source接続の追記確認.json')
    assert former['全合格']
    unchanged = ('peer/core.py', 'peer/api.py', 'peer/prices.py', 'engine/core.py',
                 'engine/interface.py', 'engine/adapter.py', 'engine/old_finance_snapshot.py', 'catalog.py', '数値設計案.json')
    for name in unchanged:
        key = str((ROOT/name).relative_to(PROJECT))
        assert before[key] == former['SHA256'][key]
    for name, wanted in former['旧独立四資料_SHA256'].items():
        assert sha(HERE/name) == wanted
    integration = read(ROOT/'engine/19入口normalとO及び支持出口の結合人工.json')
    assert integration['全合格'] and integration['新104正式金融'] == 0
    for name, wanted in integration['SHA256'].items():
        if name.endswith(('engine/core.py', 'engine/interface.py', 'peer/core.py', 'peer/api.py', 'peer/prices.py')):
            assert sha(PROJECT/name) == wanted
    source_definition = (ROOT/'prepare.py').read_text(encoding='utf-8')
    for name in ('engine/adapter.py', 'input/原本抽出前の32場登録.json', 'holdout_input/data.py', 'strategy.py', 'work/wave_v94/strategy.py'):
        assert name in source_definition
    assert '.glob(' not in ast.get_source_segment(source_definition, function(ROOT/'prepare.py', 'sources'))
    for path, name in ((ROOT/'prepare.py', 'formal'), (ROOT/'base.py', 'load_prepared')):
        assert not called(function(path, name)) & {'execute', 'play', 'simulate', 'read_npz_once'}
    lineage = function(ROOT/'base.py', 'lineage')
    lineage_text = ast.unparse(lineage)
    assert 'issubset' in lineage_text and "names['TOPIX'] == names['NK225']" in lineage_text
    assert 'glob' in called(lineage) and not called(lineage) & {'open', 'read_bytes', 'read_npz_once'}
    loader = (ROOT/'prepared_data.py').read_text(encoding='utf-8')
    assert loader.index('hashlib.sha256(saved)') < loader.index('pickle.loads') and 'base.immutable(value)' in loader
    criterion = read(ROOT/'evaluation/安定性採用判定の人工検査.json')
    assert criterion['全合格'] and criterion['正式金融読取'] == criterion['金融再生'] == 0
    for name, wanted in criterion['SHA256'].items():
        assert sha(ROOT/name) == wanted
    assessment = (ROOT/'evaluation/assessment.py').read_text(encoding='utf-8')
    assert "METRICS = ('losing_active_rate', 'downside_rms_units', 'worst_session_loss_units')" in assessment
    assert "all(value['non_worsening'] for value in comparisons.values())" in assessment
    assert 'adoption = eligible and both_80 and non_worsening and without_best' in assessment
    assert "if eligible and ident != 'OLD_G0':" in assessment
    assert "key += [-min(item['profit_share'] for item in symbols.values()), ident]" in assessment
    assert "payoff_gt_one = payoff is not None and payoff > 1." in assessment
    assert "len(active) >= 16 and total['campaigns'] >= 20" in assessment
    assert "row['session'] != best['session']" in assessment
    assert not called(function(ROOT/'evaluation/assessment.py', 'assess')) & {'read', 'load_session', 'execute', 'play', 'simulate'}
    research = (ROOT/'research.py').read_text(encoding='utf-8')
    assert 'output = interface.play' in research and 'row = accounting.account(key, output)' in research
    assert "source_curve'" in research and "growth_cohorts'" in research and "target_trace'" in research
    assert 'executor.submit(one_session' in research and research.index('interface.module(') < research.index('ThreadPoolExecutor(max_workers=workers)')
    assert before == {str(path.relative_to(PROJECT)): sha(path) for path in current}, '静的確認中にsourceが変わりました。'
    result = dict(全合格=True,
        scope='最終104入口準備と採用判定及び最終接口bindingの静的追記。既人工を保持し正式金融は未実行。',
        検査件数=dict(最終不変接口と数値source=len(unchanged), 旧独立資料保持=4, 純採用判定の既人工=criterion['検査件数'],
            継承小依存補足=5, 金融非実行関数=3, 準備保存とreadback契約=1),
        SHA256=before, 既独立追記SHA256=sha(HERE/'入口準備と最終source接続の追記確認.json'),
        旧独立四資料_SHA256=former['旧独立四資料_SHA256'],
        最終接口結合人工SHA256=sha(ROOT/'engine/19入口normalとO及び支持出口の結合人工.json'),
        正式入口準備完了証跡SHA256=sha(ROOT/'入口準備の全32結果.json'),
        結論=dict(入口='最終peer core7c694061/api274f4f4bとwrapper38fbcb55を独立小人工に接続済み。19normal id/map/資格を同一行で保ち、四reset ORと時計/seq診断を分離する。',
            source='旧103base/adapterと102strategy/data/holdoutdata及び94strategyと登録証跡を準備freezeへ補足。4旧独立証跡は上書きしていない。',
            隔離='旧32場は前回完成sessionsをそのまま使う。両商品目録一致と旧32存在を確認し、追加Dayは名前だけ検出して内容未読の別確認へ隔離する。',
            非実行='準備は保存済みpickleを読むだけで金融bodyを呼ばない。原jsonl及び103v2NPZの再読はない。',
            採用='両商品それぞれの16場20親、黒字、損小利大（無損失利益正はNone別表示）、金額80%、全3安定性非悪化、最大勝ち1場除外黒字を要求。無活動は勝ちでない。',
            順位='資格内で最悪商品赤字率・下方偏差・最大赤字・利益割合・ID。最大利益金額を順位に使わない。'),
        金融後の監査事項=['下方偏差と配置予算単位最大赤字はrootstability供給値なので、独立会計から再集計する。',
            '全configを金融前fixed catalogへ完全照合する。assessment内部はID/kind/設定合計枚数の一致を検査する。',
            '実親、全玉時価、手数料floor、未返済、片方向保有と予約上限を全数で別に検算する。'],
        実行=dict(正式32再準備=0, 新104金融=0, 金融body実行=0, 原本読取=0, NPZ読取=0,
            保存活動cache読取=0, 新追加Day内容読取=0, API=0, 実注文=0, goalツール=0),
        限界='静的接続と既人工の最終source一致。収益性・未知期間性能・全台帳の合格は主張しない。')
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 証跡=str(target), SHA256=sha(target)), ensure_ascii=False))


if __name__ == '__main__':
    main()

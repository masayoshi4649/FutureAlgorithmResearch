"""旧固定ファイルを実行せず、出口の局所変更と台帳接口を静的に記録する。"""

import ast
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'work/wave_v95'
NEW = ROOT / 'work/wave_v96'


def read(path: Path) -> dict:
    """
    機能: 旧又は新しいソースを読取だけで構文木へ変換する。
    引数: path(Path)はUTF-8のPythonファイル。
    返り値: dictは構文木とソース。import又は売買関数の実行は行わない。
    """
    text = path.read_text(encoding='utf-8')
    tree = ast.parse(text)
    compile(tree, str(path), 'exec')
    return dict(tree=tree, text=text)


def sha(path: Path) -> str:
    """
    機能: 読み取った資料の内容をSHA256へ固定する。
    引数: path(Path)。
    返り値: strは指紋。旧ファイルへ書き込まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def constants(tree: ast.Module) -> dict:
    """
    機能: 公開列と理由表のうちリテラル定義だけを抽出する。
    引数: tree(ast.Module)。
    返り値: dictは定数。値を得るためにモジュールを実行しない。
    """
    result = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                result[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return result


def functions(tree: ast.Module) -> dict:
    """
    機能: 関数ごとの位置情報を除いた構文を比較用に抽出する。
    引数: tree(ast.Module)。
    返り値: dict[str,str]は関数名と構文。数値計算は行わない。
    """
    result = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            result[node.name] = ast.dump(node, include_attributes=False)
    return result


def save(name: str, value: dict) -> None:
    """
    機能: 設計用領域だけへ読取結果を新しいJSONで保存する。
    引数: name(str)、value(dict)。
    返り値: None。95成果・原本・正式96台帳へは保存しない。
    """
    path = HERE / name
    assert path.parent == HERE
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> None:
    """
    機能: 旧入口・会計列の保持と新しい停止保護の接口を売買なしで検査する。
    引数: なし。
    返り値: Noneは静的検査及び呼出箇所設計JSON。人工損益も実行しない。
    """
    fixed_path = OLD / '事前固定.json'
    fixed = json.loads(fixed_path.read_text(encoding='utf-8'))
    paths = [OLD / name for name in ('engine.py', 'strategy.py', 'research.py', 'accounting.py')]
    paths += [ROOT / f'work/wave_v{number}/strategy.py' for number in (94, 93, 92, 91, 90)]
    paths += [ROOT / 'work/wave_v77/signals.py', fixed_path, NEW / 'engine.py', NEW / 'strategy.py', Path(__file__)]
    for path in paths:
        relative = str(path.relative_to(ROOT))
        if relative in fixed['SHA256']:
            assert sha(path) == fixed['SHA256'][relative], relative
    old_engine, new_engine = read(OLD / 'engine.py'), read(NEW / 'engine.py')
    old_strategy, new_strategy = read(OLD / 'strategy.py'), read(NEW / 'strategy.py')
    old_columns, new_columns = constants(old_engine['tree']), constants(new_engine['tree'])
    names = ('ORDER_COLUMNS', 'TRADE_COLUMNS', 'TRACE_COLUMNS', 'EVENT_COLUMNS', 'STAT_COLUMNS',
             'SLOT_COLUMNS', 'RANGE_STATE_COLUMNS', 'RISK_STATE_COLUMNS', 'RANGE_PARENT_COLUMNS',
             'PRICE_SOURCE_COLUMNS', 'REASONS', 'EVENT_CODES', 'LOSS_OBSERVATION_COLUMNS')
    assert all(old_columns[name] == new_columns[name] for name in names)
    old_functions, new_functions = functions(old_engine['tree']), functions(new_engine['tree'])
    changed = [name for name in old_functions if old_functions[name] != new_functions[name]]
    added = sorted(set(new_functions) - set(old_functions))
    assert changed == ['simulate', 'execute']
    assert added == ['trend_exit_diagnostic', 'trend_line_owner']
    old_prepared, new_prepared = functions(old_strategy['tree']), functions(new_strategy['tree'])
    assert [name for name in old_prepared if old_prepared[name] != new_prepared[name]] == ['module', 'prepare', 'play']
    for name in added:
        node = next(item for item in new_engine['tree'].body if isinstance(item, ast.FunctionDef) and item.name == name)
        comment = ast.get_docstring(node)
        assert all(word in comment for word in ('機能:', '引数:', '返り値:'))
    configuration = next(value for value in fixed['条件'] if value['id'] == 'P0_R0')
    assert configuration['trend_source'] == 'P0' and configuration['loss_reentry_kind'] == 'none'
    assert configuration['trend_budget'] == 8 and configuration['range_budget'] == 0
    assert configuration['selection'] == 'fixed' and configuration['trend_width_fraction'] == .004
    definition = dict(
        読取のみ=True, 入口='95 P0_R0の旧J8候補とJ2許可。15秒格子・中立60秒・発火間隔600秒を保持。',
        呼出順=['95 research.run_one→95 strategy.play→95 engine.execute→simulate',
                '95 prepare→94→93→92→91→90 prepare。90が旧候補を旧5秒J2許可でeventへ接続。'],
        局所箇所=[dict(資料='work/wave_v90/strategy.py', 行=112, 内容='初回から既知のref_openでD40bpを呼値切上げ、最低2呼値。'),
                  dict(資料='work/wave_v95/engine.py', 行=437, 内容='実新規fillでpeak=entry、旧stop=entry±Dとdeadlineを初期化。'),
                  dict(資料='work/wave_v95/engine.py', 行=631, 内容='期限→旧停止線判定→peak更新→D追尾更新。新床はこの最後に追加。'),
                  dict(資料='work/wave_v95/engine.py', 行=867, 内容='旧entryevent・数量・場内cut・実返済30秒後の再参加。変更しない。'),
                  dict(資料='work/wave_v95/research.py', 行=180, 内容='旧13配列の列・疎状態SHAを保持し、根の96コピーで新2診断だけ追加保存する。')],
        新設定=dict(trend_initial_stop_bp=[10, 20, 40], trend_protection_mode=[0, 1, 2], trend_hold_seconds=[1800, 0]),
        主='S10_M1_UNL', 枚数=dict(TOPIXmini=8, NK225micro=16),
        幅=dict(S='max(2, ceil(ref_open×bp/10000/tick−1e−10))×tick', D='旧trend_width。40bpを同じ場最初の価格で固定。',
                C='ceil((2floor(quantity×片道料+1e−8)/(quantity×倍率))/tick)×tick+tick',
                半分床='floor(最大有利進行÷2÷tick)×tick。ショートも方向付き幅から価格へ戻す。'),
        更新順=['次の正常BBOで実新規約定。初期stopをS線と即時D線の厳しい側へ。',
              '既知の場末返済・通常期限を旧優先順で処理。期限0は通常期限判定を行わない。',
              '新規fill行では通常停止判断を行わない。後続qokで現在のstopを先に判定。',
              '未停止の行だけ、返済側気配のpeakとD追尾を更新。',
              'mode1/2はpeak−entryの方向付き幅が2S以上でactiveを固定。',
              'mode1は費用床、mode2は費用床と最大有利進行50%床の厳しい側を追加。',
              '新stopは旧stopと全候補線の厳しい側。後退禁止。次行のstop判断へ。',
              '返済判断後はstopを更新せず次正常BBOで決済。ギャップによる床割れも実netで計上。'],
        台帳接口=dict(旧13配列='先頭の順と列の意味は変更しない。価格・数量・費用会計は旧式。',
                    trend_exit_state_trace=new_columns['TREND_EXIT_STATE_COLUMNS'],
                    trend_parent_diagnostics=new_columns['TREND_PARENT_COLUMNS'],
                    列定義キー=['trend_exit_state_columns', 'trend_parent_columns'],
                    構成線所有ビット=new_columns['TREND_LINE_OWNERS'],
                    状態保存='全原行状態は新trace変化行と元SHAで保存し疎復元する。親はfull配列保存。',
                    場末='既知場末予約のdecision_row=i−1と観測row=iは別columnで保持。'),
        共有入力='prepareはknown_from_i=0のreference_openだけ追加。playはsignal浅copyへSを差し込む。共有signal/旧原本を変更しない。',
        キャッシュ='96 strategyがNUMBA_CACHE_DIRとnumba.config.CACHE_DIRを96/numba_cacheへ限定。旧モジュールは固有名で読取。',
        必須検算=['S40/M0/H30対95P0_R0全62注文・親・全行時価・全旧状態が完全一致。',
                  'S40の全modeは各期限で経済null。保護診断の違いは許容。',
                  '各方向・S・mode・期限で、2S前後、床割れギャップ、初期SLとDの同時証拠、同clock、欠測を人工確認。',
                  '共有prepared無変更、全18入口event共通、未来prefix不変、診断の保存/疎復元一致。'],
        正式96損益実行=0, 人工売買実行=0, API取得=0, 実注文=0)
    save('出口分離の呼出箇所と台帳依存.json', definition)
    proof = dict(静的検査全合格=True, 旧公開列及び理由表保持=True, 変更既存関数=changed, 追加関数=added,
                 旧関数変更範囲='engine.simulate/execute、strategy.module/prepare/playだけ。',
                 旧95読取指紋一致=True, モジュールimport=0, 人工売買実行=0, 正式96損益実行=0, API取得=0, 実注文=0,
                 SHA256={str(path.relative_to(ROOT)): sha(path) for path in paths})
    save('局所変更と旧依存保持の静的検査.json', proof)
    print(json.dumps({key: value for key, value in proof.items() if key != 'SHA256'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

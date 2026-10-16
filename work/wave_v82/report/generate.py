"""売買反転の保存済み再生結果を、元と対比するHTMLへまとめる。"""

from pathlib import Path
import hashlib
import html
import json


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
PRIOR = BASE.parent / 'wave_v81'
ROOT = BASE.parents[1]
PUBLIC = ROOT / 'アルゴリズム調査/00078_安定赤字手法の売買反転検証'
MAIN = '安定して負ける手法の反転と全セッション損益.html'
ALL = '全188条件の前半反転比較.html'
SYMBOLS = ('TOPIX', 'NK225')


def read(path):
    """
    機能: 保存されたJSONを読み取る。
    引数: path (Path) は入力ファイル。
    返り値: dict 又はlist の保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    """
    機能: 計算資料と出力の指紋を取得する。
    引数: path (Path) は対象ファイル。
    返り値: str のSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def direction_text(model):
    """
    機能: 元の方向判定を価格幅又は板フローの数値で説明する。
    引数: model (dict) は事前固定モデル。
    返り値: str の日本語説明。天底の事後判定を入口に使わない。
    """
    parts = []
    if 'ticks' in model:
        parts.append(f'価格は初回の有効中値から±{model["ticks"]}呼値で方向を決め、以後は追跡高値・安値から{model["ticks"]}呼値戻ると反転')
    if 'span' in model:
        parts.append(f'板フローは非ゼロ変化{model["span"]}回を目安に平滑化し、比が+{model["threshold"]:g}以上で買い、−{model["threshold"]:g}以下で売り支持')
    return '。'.join(parts) + ('。価格と板が一致する時だけ方向あり' if len(parts) == 2 else '') + '。'


def describe(config, models):
    """
    機能: 元と反転の入口・途中・出口を対応させて説明する。
    引数: config (dict) は元条件、models (list) は方向モデル。
    返り値: dict の画面用説明。
    """
    entry_model = models[config['model']]
    exit_model = models[config['exit_model']]
    entry = '元は日経とTOPIXの方向が揃った側へ入り、反転ではその逆側へ入る。' + direction_text(entry_model)
    if config.get('entry_gate'):
        entry += '元条件の入口には、両市場それぞれの出口用価格方向との一致も要求する。'
    during = '保有期限・固定利確・固定損切り・固定休止は設けない。反転は出口に使う支持方向も逆にし、同じ判断構造を最初から再生する。'
    if config.get('repair'):
        during += '同方向への再参加には、有効な共同支持が一度切れた後の再成立が必要。'
    exit_text = ('両市場が有効な時、どちらかが保有と同方向でなくなれば返済。中立も含む。',
                 '有効な一市場でも保有と反対方向になれば返済。',
                 '両市場が有効で、双方が保有と反対方向なら返済。片方だけ反対・中立では継続。')[config['exit_mode']]
    if config['exit_model'] != config['model']:
        exit_text += '出口は別の方向尺度：' + direction_text(exit_model)
    exit_text = '以下の方向は、元では元の判定、反転ではその符号を逆にした判定。' + exit_text + 'セッション終了前は全返済。'
    execution = ('成行相当。発注待ちの後の有効気配で、買いは売気配、売りは買気配を使用。' if config['entry_mode'] == 0
                 else '上限付き新規。到達気配が判断時より不利1呼値以内なら約定、それを超えれば不成立。反転で不成立が変わるため、参加経路も変わり得る。返済は成行相当。')
    return dict(entry=entry, during=during, exit=exit_text, execution=execution)


def check_result(result, sessions):
    """
    機能: 保存結果の場数と商品別総会計を照合する。
    引数: result (dict) は結果、sessions (list[str]) は必要場。
    返り値: なし。不一致はAssertionErrorで生成を止める。
    """
    assert len(result['rows']) == 2 * len(sessions)
    assert set(r['session'] for r in result['rows']) == set(sessions)
    for symbol in SYMBOLS:
        rows = [r for r in result['rows'] if r['symbol'] == symbol]
        assert len(rows) == len(sessions)
        total = result['periods']['対象'][symbol]
        for field in ('profit', 'loss', 'net', 'fees', 'trades'):
            assert abs(sum(r[field] for r in rows) - total[field]) < 1e-5
        assert abs(total['profit'] - total['loss'] - total['net']) < 1e-5


def group_account(rows):
    """
    機能: 相場分類に該当する保存済み場会計だけを合計する。
    引数: rows (list[dict]) は同一商品の場会計。
    返り値: dict の利益・損失・収支・場数。取引再生や選定は行わない。
    """
    values = {key: sum(r[key] for r in rows) for key in ('profit', 'loss', 'net', 'trades', 'fees')}
    values.update(sessions=len(rows), winning_sessions=sum(r['net'] > 0 for r in rows),
                  losing_sessions=sum(r['net'] < 0 for r in rows), no_trade_sessions=sum(r['trades'] == 0 for r in rows))
    values['profit_share'] = values['profit'] / (values['profit'] + values['loss']) if values['profit'] + values['loss'] else None
    return values


def build():
    """
    機能: 事前固定代表、元188条件と反転188条件、相場分類を接続する。
    引数: なし。
    返り値: tuple(dict, dict) の主画面資料と全前半比較資料。
    """
    fixed_path = BASE / '事前固定.json'; fixed = read(fixed_path)
    old_fixed_path = PRIOR / '初回事前固定.json'; old_fixed = read(old_fixed_path)
    models_path = PRIOR / 'extended/metadata.json'; models = read(models_path)['モデル']
    regime_path = BASE / 'diagnosis/相場分類.json'; regimes = read(regime_path)
    conclusion_path = HERE / '結論文.json'; conclusion = read(conclusion_path)
    inputs = [fixed_path, old_fixed_path, models_path, regime_path, conclusion_path]
    pairs = [dict(p, description=describe(p['original'], models)) for p in fixed['pairs']]
    configs = {p[v]['id']: p[v] for p in pairs for v in ('original', 'reverse')}
    final = {}
    for delay in (0, 1, 5):
        final[str(delay)] = {}
        for method_id in configs:
            path = BASE / f'final/delay{delay}/results' / f'{method_id}.json'
            result = read(path); inputs.append(path)
            check_result(result, old_fixed['全30'])
            assert result['config']['latency'] == delay
            final[str(delay)][method_id] = result
    strict = {}
    for pair in pairs:
        method_id = pair['reverse']['id']
        if method_id not in strict:
            path = BASE / 'quality3/results' / f'{method_id}.json'
            result = read(path); inputs.append(path); check_result(result, old_fixed['全30'])
            strict[method_id] = result['periods']['対象']
    front_rows = []
    for stage in ('first', 'improved'):
        for original_path in sorted((PRIOR / stage / 'results').glob('*.json')):
            original = read(original_path); parent_id = original['config']['id']
            reverse_path = BASE / 'first/results' / f'R__{parent_id}.json'
            reverse = read(reverse_path); inputs.extend((original_path, reverse_path))
            check_result(original, old_fixed['前16']); check_result(reverse, old_fixed['前16'])
            front_rows.append(dict(parent_id=parent_id, config=original['config'], original=original['periods']['対象'], reverse=reverse['periods']['対象']))
    assert len(front_rows) == 188
    assert sum(not r['config'].get('solo') for r in front_rows) == 180
    front_diagnosis_path = BASE / 'diagnosis/前半の毎場赤字66条件を実際に反転した集計.json'
    front_diagnosis = read(front_diagnosis_path); inputs.append(front_diagnosis_path)
    grouped = {}
    for pair in pairs:
        grouped[pair['label']] = []
        for symbol in SYMBOLS:
            for regime in ('上昇', '下落', '横ばい'):
                sessions = {r['session'] for r in regimes['rows'] if r['symbol'] == symbol and r['regime'] == regime}
                record = dict(symbol=symbol, regime=regime, sessions=len(sessions))
                for variant in ('original', 'reverse'):
                    rows = final['5'][pair[variant]['id']]['rows']
                    record[variant] = group_account([r for r in rows if r['symbol'] == symbol and r['session'] in sessions])
                grouped[pair['label']].append(record)
            assert sum(r['sessions'] for r in grouped[pair['label']] if r['symbol'] == symbol) == 30
    text = read(HERE / '表示説明.json')
    text['regime-description'] = regimes['definition']
    data = dict(sessions=old_fixed['全30'], pairs=pairs, final=final, strict=strict, regimes=grouped, front_diagnosis=front_diagnosis,
                conclusion=conclusion, text=text)
    data['audit'] = {'入力': {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                     '代表枠数': len(pairs), '独立した代表数': len({p['parent_id'] for p in pairs}), '前半全条件数': len(front_rows)}
    return data, dict(rows=front_rows)


# ----------------------------------------
def render(template_name, data, script_name):
    """
    機能: テンプレートへ会計JSON・CSS・操作コードを埋め込む。
    引数: template_name (str)、data (dict)、script_name (str)。
    返り値: str の単独で表示できるHTML。
    """
    serialized = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<' + chr(92) + '/')
    return ((HERE / template_name).read_text(encoding='utf-8')
            .replace('__STYLE__', (HERE / 'style.css').read_text(encoding='utf-8'))
            .replace('__DATA__', serialized).replace('__COMMON__', (HERE / 'common.js').read_text(encoding='utf-8'))
            .replace('__SCRIPT__', (HERE / script_name).read_text(encoding='utf-8'))
            .replace('__MAIN__', html.escape(MAIN)).replace('__ALL__', html.escape(ALL)))


def main():
    """
    機能: 確定した資料から今回の公開HTML二枚を生成する。
    引数: なし。
    返り値: なし。旧調査と生データは変更しない。
    """
    data, all_data = build(); PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / MAIN).write_text(render('template.html', data, 'main.js'), encoding='utf-8')
    (PUBLIC / ALL).write_text(render('all_template.html', all_data, 'all.js'), encoding='utf-8')
    (HERE / '描画資料.json').write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    audit = dict(data['audit']); audit['出力'] = {name: digest(PUBLIC / name) for name in (MAIN, ALL)}
    (HERE / '生成結果.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'公開先': str(PUBLIC), '出力': audit['出力']}, ensure_ascii=False))


if __name__ == '__main__':
    main()

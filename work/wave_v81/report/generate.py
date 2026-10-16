"""時間期限を持たない方向追従の説明と、保存された全セッション損益を描画する。"""

from pathlib import Path
import hashlib
import html
import json


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
PUBLIC = ROOT / 'アルゴリズム調査/00077_保有時間を決めない二市場方向追従'
MAIN = '時間で区切らない方向追従と全セッション損益.html'
ALL = '全条件の前半比較.html'


def read(path):
    """
    機能: 保存済みJSONを読み取る。
    引数: path (Path) は入力ファイル。
    返り値: dict 又はlist の保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    """
    機能: 入出力の内容指紋を取得する。
    引数: path (Path) は対象ファイル。
    返り値: str のSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def direction_description(model):
    """
    機能: 方向モデルを平易な日本語へ翻訳する。
    引数: model (dict) は事前固定モデル。
    返り値: str の方向判定説明。未観測の天底で判断したとは表現しない。
    """
    pieces = []
    if 'ticks' in model:
        pieces.append(f'初回は最初の有効中値から±{model["ticks"]}呼値動いた側を価格方向とし、以後は追跡高値・安値から{model["ticks"]}呼値戻った時に反転する')
    if 'span' in model:
        pieces.append(f'板の変化{model["span"]}回を目安に平滑化したフロー比が+{model["threshold"]:g}以上なら買い、−{model["threshold"]:g}以下なら売りを支持方向とする')
    return '。'.join(pieces) + ('。価格と板が一致する時だけ方向あり' if len(pieces) == 2 else '') + '。'


def describe(config, group, models):
    """
    機能: 入口・途中・出口と注文方法を説明する。
    引数: config (dict)、group (str)、models (list) は固定された仕様。
    返り値: dict の画面用説明。保有秒数を目標として使わない。
    """
    m, x = models[config['model']], models[config['exit_model']]
    solo = bool(config.get('solo'))
    exit_text = ('両市場が有効な時、共同支持が消えたら返済。不一致・中立も含む。',
                 '有効な一市場でも保有と反対方向になったら返済。',
                 '両市場が有効で、保有と反対方向に揃ったら返済。片方だけ反対・中立では継続。')[config['exit_mode']]
    if solo:
        exit_text = ('自己市場の支持が消えたら返済。有効な中立と反対方向を含む。' if config['exit_mode'] == 0
                     else '自己市場が有効で、保有と反対方向へ変わったら返済。有効な中立だけでは返済しない。')
        exit_text += '相手の方向内容は使わない。'
    entry = ('自己市場の方向が出たら、その向きに新規。' if solo else '日経とTOPIXの方向が揃ったら、その向きに新規。')
    entry += direction_description(m)
    if config.get('entry_gate', 0):
        entry += ('さらに入口時点で、自己の出口用価格方向も新規と同じ向きであることを要求。' if solo
                  else 'さらに入口時点で、各市場の出口用価格方向も新規と同じ向きであることを要求。')
    if config['exit_model'] != config['model']:
        exit_text += '出口用の方向は別に判定：' + direction_description(x)
    if config.get('entry_gate', 0):
        exit_text += '発注待ち中に方向が崩れれば、約定直後に返済を判断することもある。'
    execution = ('新規・返済とも判断時に発注し、指定秒後の次の有効気配で買いask／売りbid。' if config['entry_mode'] == 0
                 else '新規は、到達時の気配が送信時より不利1呼値以内なら約定、範囲外は不成立。返済は指定秒後の有効気配。')
    during = '固定利確・固定損切り・保有期限・再開までの待機秒は設けない。出口の方向条件が成立するまで保有。'
    if config.get('repair', 0) == 1:
        during += '同方向への再入口には、有効な共同支持が一度切れた後の再成立を要求。'
    return dict(id=config['id'], group=group, name=m['family'] + ('・単独対照' if solo else ''),
                entry=entry, during=during, exit=exit_text, execution=execution,
                entry_model=m, exit_model=x, config=config,
                short=f'{m["id"]}／出口{x["id"]}／X{config["exit_mode"]}／M{config["entry_mode"]}')


def build():
    """
    機能: 固定代表と全条件の保存結果を接続し、会計を照合する。
    引数: なし。
    返り値: tuple(dict, dict) の主画面と前半全条件の資料。
    """
    fixed = read(BASE / '初回事前固定.json'); selected = read(BASE / '前半選定.json')
    models = read(BASE / 'extended/metadata.json')['モデル']; inputs = []; methods = []
    groups = [('初回', selected['初回']), ('再選定', selected['改修']), ('単独対照', selected['単独対照'])]
    seen = set()
    for group, configs in groups:
        for config in configs:
            if config['id'] not in seen:
                methods.append(describe(config, group, models)); seen.add(config['id'])
            else:
                matched = next(m for m in methods if m['id'] == config['id'])
                matched['group'] += '・' + group
    assert seen == {c['id'] for c in selected['確認条件']}
    final = {}
    for delay in (0, 1, 5):
        final[str(delay)] = {}
        for m in methods:
            path = BASE / 'final' / f'delay{delay}' / 'results' / f'{m["id"]}.json'
            result = read(path); inputs.append(path)
            assert len(result['rows']) == 60 and result['config']['latency'] == delay
            assert set(r['session'] for r in result['rows']) == set(fixed['全30'])
            for symbol in ('TOPIX', 'NK225'):
                rows = [r for r in result['rows'] if r['symbol'] == symbol]
                for field in ('profit', 'loss', 'net', 'trades', 'fees'):
                    assert abs(sum(r[field] for r in rows) - result['periods']['対象'][symbol][field]) < 1e-5
                for period in result['periods'].values():
                    assert sum(period[symbol]['hold_bins']) == period[symbol]['trades']
            final[str(delay)][m['id']] = result
    strict = {}
    for config in selected['改修']:
        path = BASE / 'quality3/results' / f'{config["id"]}.json'
        result = read(path); inputs.append(path)
        assert len(result['rows']) == 60
        strict[config['id']] = result['periods']['対象']
    all_rows = []
    for stage, label in (('first', '初回'), ('improved', '改修')):
        paths = sorted((BASE / stage / 'results').glob('*.json'))
        assert len(paths) == (len(fixed['条件']) if stage == 'first' else len(read(BASE / '改修前固定.json')['条件']))
        for path in paths:
            result = read(path); inputs.append(path)
            assert set(r['session'] for r in result['rows']) == set(fixed['前16'])
            config = result['config']; description = describe(config, label, models)
            all_rows.append(dict(stage=label, config=config, description=description, metrics=result['periods']['前16']))
    theory = read(BASE / 'theory/時間で切らない方向状態の仮説と反証.json')
    conclusion = read(HERE / '結論文.json')
    data = dict(sessions=fixed['全30'], front=fixed['前16'], back=fixed['後14'], methods=methods,
                initial=[c['id'] for c in selected['初回']], repaired=[c['id'] for c in selected['改修']],
                controls=[c['id'] for c in selected['単独対照']], final=final, strict=strict,
                sources=theory['一次研究'], conclusion=conclusion, count=len(all_rows), models=models,
                quality_fix=fixed['品質修正'])
    data['audit'] = {'入力': {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                     '方法数': len(methods), '全場数': 30, '前半全条件数': len(all_rows)}
    return data, dict(rows=all_rows, count=len(all_rows), models=models)


# ----------------------------------------
def render(template_name, data, script_name):
    """
    機能: HTMLへCSS・結果JSON・JavaScriptを埋め込む。
    引数: template_name (str)、data (dict)、script_name (str)。
    返り値: str のローカルで単独表示できるHTML。
    """
    serialized = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    serialized = serialized.replace('</', '<' + chr(92) + '/')
    return ((HERE / template_name).read_text(encoding='utf-8')
            .replace('__STYLE__', (HERE / 'style.css').read_text(encoding='utf-8'))
            .replace('__DATA__', serialized)
            .replace('__COMMON__', (HERE / 'common.js').read_text(encoding='utf-8'))
            .replace('__SCRIPT__', (HERE / script_name).read_text(encoding='utf-8'))
            .replace('__MAIN__', html.escape(MAIN)).replace('__ALL__', html.escape(ALL)))


def main():
    """
    機能: 今回の公開フォルダへHTML二枚と生成証拠を保存する。
    引数: なし。
    返り値: なし。過去成果・注文プログラム・計算結果は変更しない。
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

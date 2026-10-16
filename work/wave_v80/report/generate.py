"""秒売買の既存再生結果から、外部依存のない短いダークHTMLを生成する。"""

from pathlib import Path
import hashlib
import html
import json


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
PUBLIC = ROOT / 'アルゴリズム調査/00076_5秒発注遅延を含む秒スキャルピング'
MAIN = '秒スキャルピングの改善と全セッション損益.html'
ALL = '全330条件の前半比較.html'
FAMILY = ('単独OFI先行', '二市場OFI先行', '共同価格追随', '先行追随',
          '押し戻し後フロー反転', '失速逆張', '同価格表示回復', '無方向交互')
MODE = ('成行', '上限付き', '待機指値')


def read(path):
    """
    機能: 保存済みJSONを読み取る。
    引数: path (Path) は入力ファイル。
    返り値: dict 又はlist の保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    """
    機能: 入力・出力の一致確認用ハッシュを取得する。
    引数: path (Path) はファイル。
    返り値: str のSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def method(config, group):
    """
    機能: 固定条件を短い日本語の入口・保有・出口へ翻訳する。
    引数: config (dict) は固定条件、group (str) は比較上の分類。
    返り値: dict の説明。損益順位に合わせて説明を差し替えない。
    """
    identifier = config['id']; mode = config['entry_mode']
    if config['signal'] == 2:
        name = '共同進行・' + MODE[mode]
        entry = '両指数が直近10秒で同方向へ1呼値以上進み、両方の板フローも支持。3秒続いたら入る。'
        exact = '方向dについて双方d×R10≥1、双方d×F10≥0.1。3秒持続と双方の参照原本更新を要求。'
    elif config['signal'] == 5:
        name = ('失速反転・' if group == '改修' else '失速反転3秒確認・') + MODE[mode]
        entry = '直近30秒で3呼値以上進んだ方向が失速し、自己の板フローが反転を支持、相手も反対しない時に逆方向へ入る。'
        if group == '改修':
            entry += '3秒の持続確認を待たない。'
        else:
            entry += '3秒持続と両原本の更新を待つ。'
        exact = '新方向dについて−d×R30≥3、直近10秒の高安が前20秒の旧極値を更新せず現在も戻る。自己d×F10≥0.1、相手≥0。'
    else:
        name = '無方向交互・' + MODE[mode]
        entry = '30秒ごとに買い・売りを交互にする。板品質と更新条件は同じで、方向情報の価値を比較する。'
        exact = '信号格子の開始から30秒区間ごとに方向を交互化。3秒持続と双方の参照更新を要求。'
    if config.get('repair_mode') == 2:
        name = '共同進行・待機指値＋反対返済'
    execution = (
        '発注待ちの後、買いは売気配・売りは買気配で約定。',
        '到着時の気配が送信時より不利1呼値以内なら約定。範囲外なら不成立。',
        '送信時の買気配へ買指値／売気配へ売指値。到着後に相手気配が1呼値貫通した時だけ当初指値で約定。'
    )[mode]
    during = f'追加建てなし。返済後{config["cooldown"]}秒は新規を待つ。'
    exit_text = f'返済側気配で{config["target"]}呼値の利確／{config["stop"]}呼値の損切り、又は保有{config["hold"]}秒で返済判断。その後も発注待ちがある。'
    if config.get('repair_mode') == 2:
        exit_text += '反対の共同進行が確認された時も返済する。'
    return dict(id=identifier, group=group, name=name, entry=entry, during=during,
                exit=exit_text, execution=execution, exact=exact, config=config)


def build():
    """
    機能: 固定された11方法の全30場・3遅延と、全330条件の前半結果を接続する。
    引数: なし。
    返り値: tuple(dict, dict) の主レポート資料と全条件資料。
    """
    fixed = read(BASE / '初回事前固定.json'); selected = read(BASE / '最終前半選定.json')
    inputs, methods, final = [], [], {}
    for group in ('初回', '改修', '少数黒字', '無方向対照'):
        for config in selected[group]:
            methods.append(method(config, group))
    assert len(methods) == 11 and len({m['id'] for m in methods}) == 11
    for delay in (0, 1, 5):
        final[str(delay)] = {}
        for item in methods:
            path = BASE / 'final' / f'delay{delay}' / 'results' / (item['id'] + '.json')
            result = read(path)
            assert len(result['rows']) == 60
            assert set(r['session'] for r in result['rows']) == set(fixed['全30'])
            assert result['config']['latency'] == delay
            for symbol in ('TOPIX', 'NK225'):
                rows = [r for r in result['rows'] if r['symbol'] == symbol]
                for field in ('profit', 'loss', 'net', 'fees', 'trades'):
                    assert abs(sum(r[field] for r in rows) - result['periods']['対象'][symbol][field]) < 1e-5
            final[str(delay)][item['id']] = result
            inputs.append(path)
    all_rows = []
    for stage, label, count in (('first', '初回', 288), ('repair', '改修', 42)):
        paths = sorted((BASE / stage / 'results').glob('*.json')); assert len(paths) == count
        for path in paths:
            result = read(path); config = result['config']
            assert set(r['session'] for r in result['rows']) == set(fixed['前16'])
            all_rows.append(dict(stage=label, config=config, family=FAMILY[config['signal']],
                                 mode=MODE[config['entry_mode']], metrics=result['periods']['前16']))
            inputs.append(path)
    theory = read(BASE / 'theory_data/研究と検証設計.json')
    loss = read(BASE / 'theory_data/初回288条件の損失構造.json')
    explanations = read(BASE / 'theory_data/初回原因と追加案.json')
    diagnosis_path = BASE / 'diagnosis/最終代表の改善限界と遅延経路.json'
    diagnosis = read(diagnosis_path); inputs.append(diagnosis_path)
    loss_case = {k: v for k, v in diagnosis['最大損失の具体的経路'].items()
                 if k not in ('原本連続観測', '特徴時点の観測')}
    waits = {symbol: diagnosis['成行の実待ち時間'][f'A6_P6_M0|遅れ5|全30|{symbol}']
             for symbol in ('TOPIX', 'NK225')}
    strict = {}
    for item in methods:
        path = BASE / 'quality_strict3/results' / (item['id'] + '.json')
        result = read(path)
        assert len(result['rows']) == 60
        strict[item['id']] = result['periods']['対象']
        inputs.append(path)
    main = dict(sessions=fixed['全30'], front=fixed['前16'], back=fixed['後14'], methods=methods,
                initial=[c['id'] for c in selected['初回']], repaired=[c['id'] for c in selected['改修']],
                sparse=[c['id'] for c in selected['少数黒字']], control=[c['id'] for c in selected['無方向対照']],
                final=final, strict=strict, sources=theory['一次研究'], explanations=explanations,
                loss_case=loss_case, waits=waits,
                loss_basis=[r for r in loss['全条件'] if r['id'] == 'S3_P6_M0_C5'])
    conclusion = HERE / '結論文.json'
    main['conclusion'] = read(conclusion) if conclusion.exists() else {
        '主文': '発注を5秒待つ秒売買で、両商品に安定して利益が残る方法は確認できませんでした。',
        '補足': '改修による損失減と、失った利益の両方を比較します。少数取引の黒字を安定性の証拠にはしません。'
    }
    main['audit'] = {'入力': {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                     '全30': len(fixed['全30']), '主代表': 6, '全方法': 11, '遅延': [0, 1, 5], '前半全条件': len(all_rows)}
    return main, dict(rows=all_rows, families=list(FAMILY), main=MAIN)


# ----------------------------------------
def render(template_name, data, script_name):
    """
    機能: CSSとデータとJavaScriptをHTML内に埋め込む。
    引数: template_name (str)、data (dict)、script_name (str)。
    返り値: str の単独HTML。ローカルファイルから直接表示可能。
    """
    template = (HERE / template_name).read_text(encoding='utf-8')
    serialized = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    serialized = serialized.replace('</', '<' + chr(92) + '/')
    return (template.replace('__STYLE__', (HERE / 'style.css').read_text(encoding='utf-8'))
            .replace('__DATA__', serialized)
            .replace('__COMMON__', (HERE / 'common.js').read_text(encoding='utf-8'))
            .replace('__SCRIPT__', (HERE / script_name).read_text(encoding='utf-8'))
            .replace('__MAIN__', html.escape(MAIN)).replace('__ALL__', html.escape(ALL)))


def main():
    """
    機能: 新公開フォルダにHTML二枚と、生成入力の指紋を保存する。
    引数: なし。
    返り値: なし。既存番号の成果や売買計算を変更しない。
    """
    data, all_data = build(); PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / MAIN).write_text(render('template.html', data, 'main.js'), encoding='utf-8')
    (PUBLIC / ALL).write_text(render('all_template.html', all_data, 'all.js'), encoding='utf-8')
    (HERE / '描画資料.json').write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    audit = dict(data['audit']); audit['出力'] = {name: digest(PUBLIC / name) for name in (MAIN, ALL)}
    (HERE / '生成結果.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'保存先': str(PUBLIC), '出力': audit['出力']}, ensure_ascii=False))


if __name__ == '__main__':
    main()

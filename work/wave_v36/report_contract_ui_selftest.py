"""実レポートの表示JavaScriptを、人工429条件で先に検査する。"""

import ast
from pathlib import Path

from bs4 import BeautifulSoup

import report_contract_audit as audit


def main() -> None:
    """機能: 全364表示操作の正常動作と属性・論理・表示文字の破損拒否を記録する。

    引数: なし。返り値: なし (None)。実損益ファイルは読まない。
    """
    path = audit.HERE/'report_band.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    scripts = [node.value.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'script' for target in node.targets)
        and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
    assert len(scripts) == 1
    script = scripts[0]
    specs = audit.design.conditions() + audit.design.supplementary_conditions()
    html = '<select id="signal-filter">' + ''.join(
        '<option value="'+identifier+'"'+(' selected' if identifier == 'Q034' else '')+'>'+identifier+'</option>'
        for identifier in sorted({spec['signal_id'] for spec in specs})) + '</select>'
    html += '<select id="role-filter"><option value="primary" selected>基本</option><option value="diagnostic">診断</option><option value="supplementary">補助</option><option value="">全て</option></select>'
    for spec in specs:
        role = 'supplementary' if spec.get('supplementary') else 'primary' if spec['primary'] else 'diagnostic'
        html += '<details class="method" id="'+spec['id']+'" data-signal="'+spec['signal_id']+'" data-role="'+role+'"></details>'
    html += '<script>'+script+'</script>'
    result = audit.filter_contract(BeautifulSoup(html, 'html.parser'), specs)
    assert result['操作数'] == 364
    corrupted = [html.replace('data-role="primary"', 'data-role="diagnostic"', 1),
        html.replace('.some(k=>', '.every(k=>'), html.replace("n+'条件を表示'", "(n+1)+'条件を表示'")]
    refused = 0
    for text in corrupted:
        assert text != html
        try:
            audit.filter_contract(BeautifulSoup(text, 'html.parser'), specs)
        except AssertionError:
            refused += 1
    assert refused == 3
    paths = [path, Path(__file__), audit.HERE/'report_contract_audit.py', audit.HERE/'band_design.py']
    audit.save(audit.HERE/'report_contract_ui_selftest.json', dict(全人工合格=True,
        人工条件数=429, 全表示操作数=364, 破損拒否数=refused, 実JavaScript抽出=True,
        新損益読取=False, 売買再生=False, API取得数=0,
        SHA256={path.relative_to(audit.ROOT).as_posix(): audit.digest(path) for path in paths}))
    print('人工429条件の364表示操作と3破損拒否が一致', flush=True)


if __name__ == '__main__':
    main()

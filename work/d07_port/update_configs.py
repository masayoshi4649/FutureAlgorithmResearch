"""配布済み日経設定の手法IDだけを、ユーザー指定のD07へ更新する。"""

from copy import deepcopy
from pathlib import Path
import json
import re
import tomllib

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'App/SessionTrader'


def replace_methods(text, web):
    """手法キーだけを置換し、枚数・運転モード・保存先を維持する。

    引数: text(str)は元TOML、web(bool)は複数商品形式。
    返り値: strは日経day/nightをD07へ変更した本文。
    """
    if web:
        parts = re.split(r'(?m)(?=^\[\[instruments\]\]\s*$)', text)
        for index in range(1, len(parts)):
            parsed = tomllib.loads(parts[index])['instruments'][0]
            if parsed['product'].startswith('NK225'):
                parts[index] = re.sub(r'(?m)^(\s*(?:day|night)\s*=\s*)([\'\"])[^\r\n]*?\2', lambda m: m[1] + '"D07"', parts[index])
        return ''.join(parts)
    in_methods = False
    lines = []
    for line in text.splitlines(keepends=True):
        if line.strip().startswith('['):
            in_methods = line.strip() == '[methods]'
        if in_methods:
            line = re.sub(r'^(\s*(?:day|night)\s*=\s*)([\'\"])[^\r\n]*?\2', lambda m: m[1] + '"D07"', line)
        lines.append(line)
    return ''.join(lines)


def main():
    """Windows/Linuxの既存設定を退避して手法だけ更新する。

    引数: なし。返り値: None。全設定の差分が手法のみであることをassertで確認する。
    """
    changed = []
    for platform in ('windows-amd64', 'linux-amd64'):
        for product in ('NK225', 'NK225mini', 'NK225micro', 'Web'):
            path = APP / 'dist' / platform / product / 'conf/settings.toml'
            if not path.exists():
                continue
            text = path.read_text(encoding='utf-8-sig')
            before = tomllib.loads(text)
            expected = deepcopy(before)
            if product == 'Web':
                for instrument in expected['instruments']:
                    if instrument['product'].startswith('NK225'):
                        instrument['day'] = instrument['night'] = 'D07'
            else:
                expected['methods']['day'] = expected['methods']['night'] = 'D07'
            updated = replace_methods(text, product == 'Web')
            assert tomllib.loads(updated) == expected, path
            backup = Path(__file__).parent / 'config_before' / platform / product / 'settings.toml'
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                backup.write_text(text, encoding='utf-8')
            path.write_text(updated, encoding='utf-8')
            changed.append(str(path.relative_to(ROOT)))
    (Path(__file__).parent/'設定更新.json').write_text(json.dumps({'変更':'日経のday/nightだけD07','枚数とdryrunとその他設定':'変更なし','files':changed}, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()

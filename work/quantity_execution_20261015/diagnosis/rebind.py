"""根が通知した登録用表現の修正後に、旧診断計画を保全して九源へ再接続する。"""

import json

import reader


def main() -> None:
    """
    機能: 結果本文を読む前に、旧計画と新源指紋の変更理由を保存する。
    引数: なし。
    返り値: None。経済の再検査や金融の再実行はしない。
    """
    old = reader.PLAN.read_bytes()
    archive = reader.HERE / 'archive/登録metadata再接続前の診断計画.json'
    assert not archive.exists()
    archive.parent.mkdir(exist_ok=True)
    archive.write_bytes(old)
    fixed = json.loads(old.decode('utf-8'))
    previous = fixed['source_SHA256']
    current = reader.sources()
    changed = [path for path in current if current[path] != previous[path]]
    assert changed and all(path.endswith(('/plan.py', '/finance.py')) for path in changed)
    fixed['source_SHA256'] = current
    fixed['再接続'] = dict(旧計画SHA256=reader.digest(old), 変更source=changed,
        根の通知='Day quiet_windows空構造に関する登録metadata表現だけを修正。economic7源/time_policy/main不変。',
        経済再検査=0, 金融再実行=0, 結果本文読=0)
    reader.PLAN.write_text(json.dumps(fixed, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    reader.write(reader.HERE / '登録metadata再接続の証跡.json', dict(全合格=True,
        旧計画SHA256=reader.digest(old), 新計画SHA256=reader.digest(reader.PLAN.read_bytes()),
        旧source_SHA256=previous, 新source_SHA256=current, 変更source=changed,
        経済再検査=0, 金融再実行=0, 結果本文読=0))
    print(json.dumps(dict(全合格=True, 計画SHA256=reader.digest(reader.PLAN.read_bytes()), 変更source=changed), ensure_ascii=False))


if __name__ == '__main__':
    main()

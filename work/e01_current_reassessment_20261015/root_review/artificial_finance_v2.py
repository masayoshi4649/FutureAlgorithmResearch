"""初版の保存人工を保ち、最終sourceで同じ保存経路を新しい証跡へ接続する。"""

from pathlib import Path


def main() -> None:
    """
    機能: 既存の合成素材を変更せず、現sourceの最終保存統合を別保存先へ実行する。
    引数: なし。
    返り値: None。初版証跡を上書きせず、実入力を読まない。
    """
    here=Path(__file__).resolve().parent
    path=here/'artificial_finance.py'
    source=path.read_text(encoding='utf-8')
    changes={
        "destination=HERE/'人工保存統合'":"destination=HERE/'人工保存統合_v2'",
        "paths.append(Path(__file__).resolve())":"paths.append(Path(__file__).resolve());paths.append(HERE/'artificial_finance.py')",
        "HERE/'根の一次台帳と未知保持及び最終JSON保存の純人工.json'":"HERE/'根の一次台帳と未知保持及び最終JSON保存の純人工_v2.json'"
    }
    for old,new in changes.items():
        assert source.count(old)==1
        source=source.replace(old,new)
    namespace={'__name__':'__main__','__file__':str(Path(__file__).resolve())}
    exec(compile(source,str(path),'exec'),namespace)


if __name__=='__main__':
    main()

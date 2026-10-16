"""最終の経済sourceと準備guardを保存統合の合成素材へ再接続する。"""

from pathlib import Path


def main() -> None:
    """
    機能: 初版素材を同じまま現sourceで保存し、前版証跡を保持する。
    引数: なし。
    返り値: None。実inputと金融には触れない。
    """
    here=Path(__file__).resolve().parent
    path=here/'artificial_finance.py'
    source=path.read_text(encoding='utf-8')
    changes={
        "destination=HERE/'人工保存統合'":"destination=HERE/'人工保存統合_v4'",
        "paths.append(Path(__file__).resolve())":"paths.append(Path(__file__).resolve());paths.append(HERE/'artificial_finance.py')",
        "HERE/'根の一次台帳と未知保持及び最終JSON保存の純人工.json'":"HERE/'根の一次台帳と未知保持及び最終JSON保存の純人工_v4.json'"
    }
    for old,new in changes.items():
        assert source.count(old)==1
        source=source.replace(old,new)
    namespace={'__name__':'__main__','__file__':str(Path(__file__).resolve())}
    exec(compile(source,str(path),'exec'),namespace)


if __name__=='__main__':
    main()

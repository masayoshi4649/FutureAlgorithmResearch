"""00048の保存データ研究を、現在APIなしで再実行する。"""

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'work/wave_v51'
TASKS = {
    'report': ['build_report.py'],
    'trace': ['raw_trace/trace.py', 'raw_trace/verify.py'],
    'intervals': ['interval_audit/run_all.py'],
    'properties': ['properties_e01/analyze.py', 'properties_price/analysis.py',
                   'properties_price/verify.py', 'properties_price/report.py', 'properties_price/quality.py',
                   'properties_book/analyze.py',
                   'properties_book/overlap_diagnostic.py', 'build_report.py'],
}


def main() -> None:
    """機能: 指定した研究を同じPythonで順に起動し、失敗時は停止する。

    引数: CLI --task(str、既定report)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser(description='00048 保存データによる性質と損益の検証')
    parser.add_argument('--task', choices=TASKS, default='report', help='実行内容')
    args = parser.parse_args()
    for relative in TASKS[args.task]:
        script = WORK / relative
        if not script.is_file():
            raise FileNotFoundError(f'研究コードがありません: {script}')
        print(f'実行: {relative}', flush=True)
        subprocess.run([sys.executable, '-X', 'utf8', str(script)], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()

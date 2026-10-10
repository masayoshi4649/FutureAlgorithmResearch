"""共通起動ファイルの引数・終了コード・外部フォルダからの実行を検証する。"""

import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


START = Path(__file__).resolve().parents[1] / 'start.py'


def load_start():
    """機能: 起動ファイルを実行せずモジュールとして読み込む。

    引数: なし。返り値: 起動モジュール(ModuleType)。
    """
    spec = importlib.util.spec_from_file_location('papertrade_start_test', START)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StartTests(unittest.TestCase):
    def test_help_from_local_and_external_directory(self):
        """機能: 自フォルダ・外部フォルダから通信なしで引数案内を表示できる。

        引数: self(StartTests)。返り値: なし(None)。
        """
        with tempfile.TemporaryDirectory() as directory:
            for cwd in (START.parent, Path(directory)):
                with self.subTest(cwd=str(cwd)):
                    result = subprocess.run([sys.executable, str(START), '--help'], cwd=cwd,
                                            capture_output=True, encoding='utf-8', timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('--output', result.stdout)
                    self.assertIn('実注文は発行しません', result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_import_has_no_start_or_stream_changes(self):
        """機能: importだけでは運転や標準出力の設定変更を始めない。

        引数: self(StartTests)。返り値: なし(None)。
        """
        fake = types.ModuleType('papertrade.runtime')
        fake.main = Mock()
        stream = Mock()
        with patch.dict(sys.modules, {'papertrade.runtime': fake}), \
                patch('sys.stdout', stream), patch('sys.stderr', stream):
            load_start()
        fake.main.assert_not_called()
        stream.reconfigure.assert_not_called()
        stream.write.assert_not_called()

    def test_arguments_and_working_directory_are_preserved(self):
        """機能: 相対保存先などの引数と呼出元の作業ディレクトリを維持する。

        引数: self(StartTests)。返り値: なし(None)。
        """
        module = load_start()
        argv = ['--output', './試運転', '--seconds', '180', '--fill-mode', 'observed']
        before = Path.cwd()
        fake = types.ModuleType('papertrade.runtime')
        fake.main = Mock(return_value=0)
        with patch.dict(sys.modules, {'papertrade.runtime': fake}), \
                patch('sys.stdout', io.StringIO()), patch('sys.stderr', io.StringIO()):
            self.assertEqual(module.main(argv), 0)
        fake.main.assert_called_once_with(argv)
        self.assertEqual(Path.cwd(), before)

    def test_nonzero_exit_code_reaches_shell(self):
        """機能: 運転側の終了コード2をシェルへ同じ値で返す。

        引数: self(StartTests)。返り値: なし(None)。
        """
        script = ("import runpy,sys,types; m=types.ModuleType('papertrade.runtime'); "
                  "m.main=lambda argv: 2; sys.modules['papertrade.runtime']=m; "
                  "runpy.run_path(sys.argv[1],run_name='__main__')")
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-c', script, str(START)], cwd=directory,
                                    capture_output=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertIn('終了コード 2', result.stderr)

    def test_exception_leaves_traceback(self):
        """機能: 例外の原因と発生箇所を標準エラーへ残す。

        引数: self(StartTests)。返り値: なし(None)。
        """
        module = load_start()
        fake = types.ModuleType('papertrade.runtime')
        fake.main = Mock(side_effect=ValueError('検証用エラー'))
        error = io.StringIO()
        with patch.dict(sys.modules, {'papertrade.runtime': fake}), \
                patch('sys.stdout', io.StringIO()), patch('sys.stderr', error):
            self.assertEqual(module.main([]), 1)
        self.assertIn('仮想トレードを停止しました: 検証用エラー', error.getvalue())
        self.assertIn('Traceback', error.getvalue())
        self.assertIn('ValueError', error.getvalue())


if __name__ == '__main__':
    unittest.main()

import unittest
from unittest.mock import MagicMock, patch, mock_open
import sys
from pathlib import Path

# Add the scripts directory to sys.path to resolve truss.py imports
scripts_dir = str(Path(__file__).resolve().parent.parent.parent / 'scripts')
if scripts_dir not in sys.path:
    sys.path.append(scripts_dir)

import truss

class TestTrussCLIProxy(unittest.TestCase):
    @patch('truss.is_port_open')
    def test_cmd_start_already_running(self, mock_is_port_open):
        mock_is_port_open.return_value = True
        
        args = MagicMock()
        args.port = 8000
        args.policy = None
        
        with patch('builtins.print') as mock_print:
            truss.cmd_start(args)
            mock_print.assert_any_call('🛡️ Truss Audit Proxy is already running on port 8000.')

    @patch('truss.is_port_open')
    @patch('subprocess.Popen')
    def test_cmd_start_successful(self, mock_popen, mock_is_port_open):
        # First check returns False (not running), subsequent checks return True (starts running)
        mock_is_port_open.side_effect = [False, True, True, True, True]
        
        args = MagicMock()
        args.port = 8000
        args.policy = None
        
        mock_log = mock_open()
        with patch('builtins.open', mock_log),              patch('builtins.print') as mock_print:
            truss.cmd_start(args)
            mock_popen.assert_called_once()
            mock_print.assert_any_call('🛡️ Truss Audit Proxy daemon successfully started on port 8000.')

    @patch('truss.is_port_open')
    def test_cmd_kill_inactive(self, mock_is_port_open):
        mock_is_port_open.return_value = False
        
        args = MagicMock()
        args.port = 8000
        
        with patch('builtins.print') as mock_print:
            truss.cmd_kill(args)
            mock_print.assert_any_call('🛡️ No Truss Audit Proxy running on port 8000.')

    @patch('truss.is_port_open')
    @patch('subprocess.check_output')
    @patch('os.kill')
    def test_cmd_kill_active(self, mock_kill, mock_check_output, mock_is_port_open):
        # Provide plenty of values so the polling loop does not run out of items
        mock_is_port_open.side_effect = [True] + [False] * 50
        mock_check_output.return_value = '12345'
        
        args = MagicMock()
        args.port = 8000
        
        with patch('builtins.print') as mock_print:
            truss.cmd_kill(args)
            mock_kill.assert_called_with(12345, 15) # SIGTERM
            mock_print.assert_any_call('🛡️ Sent SIGTERM to pid 12345')
            mock_print.assert_any_call('🛡️ Truss Audit Proxy stopped (port 8000).')

if __name__ == "__main__":
    unittest.main()

from greenrun.__main__ import main


def test_cli_without_command_prints_help(capsys):
    assert main([]) == 0
    assert "usage: greenrun" in capsys.readouterr().out

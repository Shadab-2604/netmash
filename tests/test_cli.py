"""
Unit tests for NetMash CLI argument parsing and options.
"""

from netmash.cli import build_parser


def test_cli_parser_defaults():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.info is False
    assert args.status is False
    assert args.nodes is False
    assert args.name is None
    assert args.port == 8765
    assert args.no_color is False


def test_cli_parser_flags():
    parser = build_parser()

    args_info = parser.parse_args(["-i"])
    assert args_info.info is True

    args_status = parser.parse_args(["-s"])
    assert args_status.status is True

    args_nodes = parser.parse_args(["-n"])
    assert args_nodes.nodes is True

    args_custom = parser.parse_args(["--name", "Shadab", "--port", "9000", "--no-color"])
    assert args_custom.name == "Shadab"
    assert args_custom.port == 9000
    assert args_custom.no_color is True


def test_cli_parser_subcommands():
    parser = build_parser()

    # group create
    args = parser.parse_args(["group", "create", "developers", "--pin"])
    assert args.subcommand == "group"
    assert args.group_action == "create"
    assert args.group_name == "developers"
    assert args.pin is True

    # group list
    args = parser.parse_args(["group", "list"])
    assert args.subcommand == "group"
    assert args.group_action == "list"

    # group join
    args = parser.parse_args(["group", "join", "developers"])
    assert args.subcommand == "group"
    assert args.group_action == "join"
    assert args.group_name == "developers"

    # dm
    args = parser.parse_args(["dm", "Shadab", "Hello there"])
    assert args.subcommand == "dm"
    assert args.target_user == "Shadab"
    assert args.message == "Hello there"

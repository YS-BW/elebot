"""elebot 命令行模块入口。"""

from elebot.cli.app import app as cli_app


def main() -> None:
    """启动 elebot 命令行。"""
    cli_app()


if __name__ == "__main__":
    main()

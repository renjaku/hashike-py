import argparse
import importlib
import io
import logging.config
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from .core import apply, default_network
from .drivers import Driver, get_driver
from .utils import URL, get_language, open_url, package_name

DEFAULT_DRIVER = 'docker'

default_log_config = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)s %(levelname)-8s %(name)-15s %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        }
    },
    'handlers': {
        'default': {
            'formatter': 'default',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout'
        }
    },
    'loggers': {
        'hashike': {
            'handlers': ['default'],
            'level': 'DEBUG',
            'propagate': False
        }
    }
}

logger = logging.getLogger(package_name)


def parse_import_module(s: str) -> ModuleType:
    try:
        return importlib.import_module(s)
    except ModuleNotFoundError as e:
        raise argparse.ArgumentTypeError(str(e))


def parse_driver(s: str) -> Driver:
    try:
        return get_driver(s)
    except KeyError:
        raise argparse.ArgumentTypeError('invalid driver')


def parse_url(s: str) -> URL:
    try:
        return URL.create(s)
    except Exception:
        raise argparse.ArgumentTypeError('invalid URL')


def parse_file(s: str):
    if s == '-':
        return io.TextIOWrapper(sys.stdin.buffer, encoding='utf8')

    return parse_url(s)


def parse_log_config(s: str) -> dict[str, Any]:
    url = parse_url(s)

    try:
        with open_url(url, encoding='utf8') as f:
            return yaml.safe_load(f)
    except Exception:
        raise argparse.ArgumentTypeError(f"""
failed to open, for the following reasons:
{traceback.format_exc()}
""".strip())


def get_local_helps() -> dict[str, str]:
    r: dict[str, str] = {}

    lang = get_language()

    if lang == 'ja':
        r['--driver'] = """
コンテナドライバ。現在は "docker" のみ。省略した場合のデフォルトも "docker"
"""
        r['--network'] = f"""
コンテナが接続する既存のネットワーク。オプション繰り返しによる複数指定可。
未指定の場合、デフォルトの "{default_network}" を作成し、接続する
"""
        r['--log-config'] = """
ロギング設定。logging.dictConfig() で読み込むため JSON と YAML のみ対応
"""
        r['--import-module'] = """
追加でインポートするモジュール。オプション繰り返しによる複数指定可。
もし、カスタムドライバを使用する場合 --driver より先に指定する必要がある
"""
        r['file'] = """
K8s Pod マニフェストに似たコンテナ定義ファイル。標準入力から取り込むなら "-" を指定する
"""
        r = {k: v.replace('\n', '') for k, v in r.items()}
    else:
        r['--driver'] = 'container driver (default: "%(default)s")'
        r['--network'] = 'existing container network(s)'
        r['--log-config'] = ('logging configuration (supported formats: json, '
                             'yaml)')
        r['--import-module'] = ('pre-import modules (if a custom driver is '
                                'used, it must be before --driver)')
        r['file'] = ('container definition file like K8s manifest. '
                     '(if reading from standard input, '
                     'specify "-" as the input source)')

    return r


def main() -> None:
    helps = get_local_helps()

    parser = argparse.ArgumentParser(Path(__file__).parent.name)

    subparsers = parser.add_subparsers(dest='subcommand', required=True)
    subparser = subparsers.add_parser('apply')
    subparser.add_argument('--driver', type=parse_driver,
                           default=get_driver(DEFAULT_DRIVER),
                           help=helps['--driver'])
    subparser.add_argument('--network', action='append', dest='networks',
                           metavar='NETWORK', help=helps['--network'])
    subparser.add_argument('--log-config', type=parse_log_config,
                           default=default_log_config,
                           help=helps['--log-config'])
    subparser.add_argument('--import-module', type=parse_import_module,
                           action='append', dest='import_modules',
                           metavar='MODULE', help=helps['--import-module'])
    subparser.add_argument('file', type=parse_file, help=helps['file'])
    subparser.set_defaults(action=apply)

    args = parser.parse_args()

    logging.config.dictConfig(args.log_config)

    logger.debug(args)

    networks = args.networks or []

    if isinstance(args.file, URL):
        with open_url(args.file, encoding='utf8') as f:
            args.action(args.driver, f, networks)
    else:
        args.action(args.driver, args.file, networks)

from collections.abc import Callable
from typing import Optional

from ..drivers import Driver, Image
from ..utils import URL

Puller = Callable[[URL, Driver], Image]

_map: dict[Optional[str], Puller] = {}


class PullerNotFoundError(Exception):
    ...


def get_puller(url_scheme: Optional[str]) -> Puller:
    try:
        return _map[url_scheme]
    except KeyError as e:
        raise PullerNotFoundError from e


def puller(*, url_scheme: Optional[str]):
    def wrap(fn: Puller):
        _map[url_scheme] = fn
        return _map[url_scheme]

    return wrap

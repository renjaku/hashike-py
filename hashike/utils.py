import importlib
import io
import locale
import os
from dataclasses import dataclass, replace
from pathlib import Path, PurePath, PurePosixPath
from typing import (IO, Literal, Optional, Type, TypeVar, Union, get_args,
                    overload)
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

import boto3

package_name = Path(__file__).parent.name

tmp_dir = Path(
    os.environ.get('temp',
                   os.environ.get('tmp',
                                  os.environ.get('tmpdir', '/tmp')))
)


def _get_language(default: str, getlocale=locale.getlocale) -> str:
    language_code, _ = getlocale()

    if language_code:
        lang, *_ = [x.lower()
                    for x in language_code.replace('_', '-').split('-', 1)]

        lang = lang[:2]

        if len(lang) == 2:
            return lang

    return default


def get_language(default: str = 'en') -> str:
    return _get_language(default)


def unparse_qs(queries: dict[str, list[str]]) -> str:
    simplified = {k: v[0] if len(v) == 1 else v for k, v in queries.items()}
    return urlencode(simplified, doseq=True)


Self = TypeVar('Self', bound='URL')


@dataclass(frozen=True)
class URL:
    scheme: Optional[str]
    username: Optional[str] = None
    password: Optional[str] = None
    hostname: Optional[str] = None
    port: Optional[int] = None
    path: Optional[PurePosixPath] = None
    query: Optional[str] = None

    @classmethod
    def create(cls: Type[Self],
               url_or_path: Union[PurePath, Self, str]) -> Self:
        if isinstance(url_or_path, PurePath):
            url_str = str(url_or_path).replace('\\', '/')
        elif isinstance(url_or_path, cls):
            return url_or_path.copy()
        elif isinstance(url_or_path, str):
            url_str = url_or_path
        else:
            raise TypeError('url_or_path cannot be of type '
                            f'{type(url_or_path)}')

        url = urlparse(url_str)

        def unq(s):
            if s is None:
                return None
            return unquote(s)

        username, password = map(unq, (url.username, url.password,))
        path = unq(url.path)

        return cls(url.scheme or None, username or None, password or None,
                   url.hostname or None, url.port or None,
                   PurePosixPath(path) if path else None,
                   url.query or None)

    @property
    def host(self: Self):
        r = self.hostname or ''

        if self.port:
            r += f':{self.port}'

        return r

    @property
    def queries(self: Self) -> Optional[dict[str, list[str]]]:
        return parse_qs(self.query)

    def replace(self: Self, /, **changes):
        return replace(self, **changes)

    def copy(self: Self):
        return self.replace()

    def __str__(self: Self):
        return urlunparse((self.scheme or '',
                           self.host,
                           str(self.path) if self.path else '',
                           '',
                           unparse_qs(self.queries) if self.queries else '',
                           ''))


def parse_image_url(url: str):
    parsed = urlparse(url)

    if parsed.scheme and parsed.hostname:
        return URL.create(url)

    parts = url.lstrip('/').split('/')

    if not parts:
        raise ValueError(f"invalid image URL '{url}'")

    if len(parts) == 1:
        return URL.create('///' + url)

    prefix, *_ = parts

    if '.' in prefix or ':' in prefix:
        return URL.create('//' + url)

    return URL.create('///' + url)


OpenTextMode = Literal['r']
OpenBinaryMode = Literal['br', 'rb']


@overload
def open_s3_url(url: URL, mode: OpenTextMode = 'r',
                encoding: Optional[str] = None) -> IO[str]:
    ...


@overload
def open_s3_url(url: URL, mode: OpenBinaryMode,
                encoding: None = None) -> IO[bytes]:
    ...


def open_s3_url(url, mode='r', encoding=None):
    if url.scheme != 's3':
        raise ValueError('URL scheme must be s3')

    if not url.hostname:
        raise ValueError('URL hostname is required')

    importlib.reload(boto3)  # for when environ vars are changed

    s3 = boto3.resource('s3')
    bucket = s3.Bucket(url.hostname)
    key = str(url.path.relative_to('/'))
    buffer = io.BytesIO()
    bucket.download_fileobj(key, buffer)
    buffer.seek(0)

    if mode in get_args(OpenTextMode):
        return io.TextIOWrapper(buffer, encoding=encoding)

    return buffer


@overload
def open_url(url: URL, mode: OpenTextMode = 'r',
             encoding: Optional[str] = None) -> IO[str]:
    ...


@overload
def open_url(url: URL, mode: OpenBinaryMode,
             encoding: None = None) -> IO[bytes]:
    ...


def open_url(url, mode='r', encoding=None):
    if url.scheme == 's3':
        return open_s3_url(url, mode, encoding=encoding)

    return open(url.path, mode, encoding=encoding)

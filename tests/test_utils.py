import os
from pathlib import Path
from urllib.parse import parse_qs

from hashike import utils

assert (_ := utils._get_language('en',
                                 lambda: ('Japanese_Japan', '932'))) == 'ja', _
assert (_ := utils. _get_language('en', lambda: ('C', 'UTF-8'))) == 'en', _

assert (_ := utils.unparse_qs(parse_qs(a := 'a=0&a=1&b=0'))) == a, _

path = Path('/path/to/file')
url = utils.URL.create(path)
assert (
    url.scheme is None
    and url.hostname is None
    and url.port is None
    and str(url.path) == '/path/to/file'
), repr(url)

url = utils.URL.create('https://www.example.com:8000/path/to/file')
assert (
    url.scheme == 'https'
    and url.hostname == 'www.example.com'
    and url.port == 8000
    and str(url.path) == '/path/to/file'
), repr(url)

url = utils.URL.create(url)
assert (
    url.scheme == 'https'
    and url.hostname == 'www.example.com'
    and url.port == 8000
    and str(url.path) == '/path/to/file'
), repr(url)

url = utils.parse_image_url('tmp')
assert (
    url.scheme is None
    and url.hostname is None
    and url.port is None
    and str(url.path) == '/tmp'
), repr(url)

url = utils.parse_image_url('tmp:latest')
assert (
    url.scheme is None
    and url.hostname is None
    and url.port is None
    and str(url.path) == '/tmp:latest'
), repr(url)

url = utils.parse_image_url('docker.io/library/tmp:latest')
assert (
    url.scheme is None
    and url.hostname == 'docker.io'
    and url.port is None
    and str(url.path) == '/library/tmp:latest'
), repr(url)

url = utils.parse_image_url('example.com:8000/path/to/tmp:latest')
assert (
    url.scheme is None
    and url.hostname == 'example.com'
    and url.port == 8000
    and str(url.path) == '/path/to/tmp:latest'
), repr(url)

url = utils.parse_image_url('docker-archive+s3://bucket/path/to/service.tar.gz'
                            '/tmp:latest')
assert (
    url.scheme == 'docker-archive+s3'
    and url.hostname == 'bucket'
    and url.port is None
    and str(url.path) == '/path/to/service.tar.gz/tmp:latest'
), repr(url)

if 'S3_MANIFEST_FILE' in os.environ:
    url = utils.URL.create(os.environ['S3_MANIFEST_FILE'])

    with utils.open_s3_url(url) as f:
        s = f.read()
    with utils.open_url(url) as f:
        assert f.read() == s

    with utils.open_s3_url(url, 'rb') as f:
        b = f.read()
    with utils.open_url(url, 'rb') as f:
        assert f.read() == b

this_script = Path(__file__)
url = utils.URL.create(this_script)

with utils.open_url(url) as f:
    assert f.read() == this_script.read_text()

with utils.open_url(url, 'rb') as f:
    assert f.read() == this_script.read_bytes()

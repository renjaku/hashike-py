import json
import tarfile
from functools import cache
from pathlib import Path

from ..drivers import Driver, EnvVar, Image
from ..utils import URL, open_url, tmp_dir
from .base import puller


@cache
def download_docker_archive_from_s3(url: URL) -> Path:
    if not url.path:
        raise ValueError

    download_path = tmp_dir / url.path.name

    with open_url(url, 'rb') as remote:
        with download_path.open('wb') as f:
            f.write(remote.read())

    return download_path


@cache
def get_images_from_docker_archive(download_path: Path) -> list[Image]:
    r: list[Image] = []

    with tarfile.open(download_path) as f:
        buff = f.extractfile('manifest.json')

        if not buff:
            raise ValueError('manifest.json was not found')

        manifest = json.load(buff)

        for item in manifest:
            image_id = 'sha256:' + item['Config'].removesuffix('.json')
            refs = item['RepoTags']

            buff = f.extractfile(item['Config'])

            if not buff:
                raise ValueError(f"{item['Config']} was not found")

            details = json.load(buff)
            environment = tuple(sorted(
                EnvVar(*env.split('=', 1))
                for env in details['config'].get('Env') or []
            ))
            entrypoint = tuple(details['config'].get('Entrypoint') or [])
            command = tuple(details['config'].get('Cmd') or [])

            r.append(Image(id=image_id, references=tuple(refs),
                           environment=environment, entrypoint=entrypoint,
                           command=command))

    return r


@puller(url_scheme='docker-archive+s3')
def pull_from_docker_archive_on_s3(url: URL, driver: Driver) -> Image:
    if not (url.scheme and url.path):
        raise ValueError

    src_url_scheme = url.scheme.removeprefix('docker-archive+')
    src_url_path = url.path.parent
    src_ref = url.path.name
    src_url = url.replace(scheme=src_url_scheme, path=src_url_path)
    download_path = download_docker_archive_from_s3(src_url)
    archive_images = get_images_from_docker_archive(download_path)

    target_image = None
    loaded = False
    existing_images = driver.get_images()

    for image in archive_images:  # アーカイブに含まれる全てのイメージ
        if src_ref in image.references:
            target_image = image

        if not loaded and image not in existing_images:  # 既存のイメージリストに存在しない場合
            with download_path.open('rb') as f:
                driver.load_docker_archive(f)  # アーカイブをロード
                loaded = True

    if not target_image:
        raise ValueError('target image was not found')

    return target_image  # URL が指すイメージ情報を返す

import time
from contextlib import contextmanager
from io import StringIO
from unittest import mock

from hashike import Context, apply
from hashike.drivers import Driver
from hashike.drivers.base import _map as driver_map


def test_apply(driver: Driver):
    def remove_all_managed_containers():
        target_names = [x.name for x in driver.get_all_managed_containers()]
        if target_names:
            driver.remove_containers(target_names)

    @contextmanager
    def cleaning():
        try:
            yield remove_all_managed_containers()
        finally:
            remove_all_managed_containers()

    patch_dl_docker_arc = mock.patch('hashike.pullers.docker_archive.'
                                     'download_docker_archive_from_s3')
    patch_get_images = mock.patch('hashike.pullers.docker_archive.'
                                  'get_images_from_docker_archive')

    with cleaning(), \
         patch_dl_docker_arc as dl_docker_arc, \
         patch_get_images as get_images:
        # マニフェストからコンテナ群を起動
        manifest = """
apiVersion: v1
kind: Hashike
metadata:
  namespace: hashike
  name: test
spec:
  containers:
  - name: hashike-test
    image: nginx:alpine-slim
""".lstrip()
        ctx = Context(driver=driver, file=StringIO(manifest), networks=[])
        result = apply(ctx)
        assert not result.removed_containers, result
        assert len(result.created_containers) == 1, result

        # 再度同じマニフェストからコンテナ群を更新
        ctx.file.seek(0)
        result = apply(ctx)
        assert not result.removed_containers, result
        assert not result.created_containers, result

        # 環境変数を追加し、コンテナ群を更新
        manifest = """
apiVersion: v1
kind: Hashike
metadata:
  namespace: hashike
  name: test
spec:
  containers:
  - name: hashike-test
    image: nginx:alpine-slim
    env:
    - name: MY_ENV
      value: test
""".lstrip()
        ctx.file = StringIO(manifest)
        result = apply(ctx)
        assert len(result.removed_containers) == 1, result
        assert len(result.created_containers) == 1, result
        assert dict(result.removed_containers[0].environment) \
            .get('MY_ENV') is None
        assert dict(result.created_containers[0].environment) \
            .get('MY_ENV') == 'test'

        # イメージ取得先を docker-archive+s3 に変更し、コンテナ群を更新
        manifest = """
apiVersion: v1
kind: Hashike
metadata:
  namespace: hashike
  name: test
spec:
  containers:
  - name: hashike-test
    image: docker-archive+s3://my-bucket/docker-archives/misc.images.tar.gz/nginx:alpine-slim
""".lstrip()  # noqa: E501
        ctx.file = StringIO(manifest)
        dl_docker_arc.return_value = None
        get_images.return_value = [driver.pull('nginx:alpine-slim')]
        result = apply(ctx)
        assert len(result.removed_containers) == 1, result
        assert len(result.created_containers) == 1, result


for driver in driver_map.values():
    print('target driver', repr(driver))
    s = time.time()
    test_apply(driver)
    print('elasped', time.time() - s, 'sec')

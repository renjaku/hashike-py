from ..drivers import Driver, Image
from ..utils import URL
from .base import PullerNotFoundError, get_puller, puller
from .docker_archive import pull_from_docker_archive_on_s3


@puller(url_scheme=None)
def pull_from_registry(url: URL, driver: Driver) -> Image:
    if not url.path:
        raise ValueError

    image = '/'.join(str(x)
                     for x in [url.hostname, url.path.relative_to('/')]
                     if x)

    if ':' not in image:
        image += ':latest'

    return driver.pull(image)


__all__ = ['PullerNotFoundError', 'get_puller', 'puller',
           'pull_from_docker_archive_on_s3', 'pull_from_registory']

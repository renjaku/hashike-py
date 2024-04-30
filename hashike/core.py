import logging.config
from dataclasses import dataclass
from typing import IO, Any, Iterable, TypeVar

import yaml

from .drivers import (Container, Driver, EnvVar, Image,
                      NetworkAlreadyExistsError, Port, Volume,
                      VolumeNotFoundError)
from .pullers import get_puller
from .utils import package_name, parse_image_url

logger = logging.getLogger(package_name)

default_network = package_name


@dataclass
class ApplyResult:
    removed_init_containers: list[Container]
    created_init_containers: list[Container]
    removed_containers: list[Container]
    created_containers: list[Container]


def _merge_envs(*envs: Iterable[EnvVar]) -> list[EnvVar]:
    return [x for x in set(y for x in envs for y in x)]


@dataclass
class _ParseContainer:
    images: dict[str, Image]
    volumes: dict[str, Volume]
    networks: list[str]
    restart_policy: str

    def __call__(self, container: dict[str, Any],
                 init: bool = False) -> Container:
        container_name = container['name']
        image = self.images[container['image']]
        command = container.get('command', image.entrypoint)
        args = container.get('args', image.command)

        ports = []
        for port in container.get('ports', []):
            port_kwargs = dict(
                container_port=port['containerPort'],
                host_ip=port.get('hostIp'),
                host_port=port.get('hostPort', port['containerPort'])
            )
            protocol = port.get('protocol')
            if protocol:
                port_kwargs['protocol'] = protocol
            ports.append(Port(**port_kwargs))
        ports = sorted(ports)

        environment = _merge_envs(image.environment,
                                  [EnvVar(env['name'], str(env['value']))
                                   for env in container.get('env', [])])
        environment = sorted(environment)

        if init and self.restart_policy == 'Always':
            # https://kubernetes.io/ja/docs/concepts/workloads/pods/init-containers/#detailed-behavior
            default_restart_policy = 'OnFailure'
        else:
            default_restart_policy = self.restart_policy
        # 本来 container.restartPolicy は、初期化コンテナのみ設定可能だが、非初期化コンテナも許容する
        # https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.30/#container-v1-core
        restart_policy = container.get('restartPolicy', default_restart_policy)

        networks = sorted(self.networks)

        mounts = []
        for mount in container.get('volumeMounts', []):
            volume = self.volumes[mount['name']]
            mounts.append(Volume(type=volume.type, source=volume.source,
                                 target=mount['mountPath']))
        mounts = sorted(mounts)

        return Container(name=container_name, image_id=image.id,
                         entrypoint=tuple(command), command=tuple(args),
                         environment=tuple(environment), ports=tuple(ports),
                         restart_policy=restart_policy,
                         networks=tuple(networks),
                         mounts=tuple(mounts))


T = TypeVar('T')


def _diff(a: list[T], b: list[T]) -> list[T]:
    diff = set(a) - set(b)
    return [x for x in a if x in diff]


def apply(driver: Driver, file: IO[str], networks: list[str]) -> ApplyResult:
    logger.debug(f'Driver: {driver}')
    logger.debug(f'File: {file}')
    logger.debug(f'Networks: {networks}')

    # マニフェストを読み込み、次の起動コンテナ情報を得る
    manifest = yaml.safe_load(file)

    init_containers = manifest['spec'].get('initContainers', [])
    containers = manifest['spec']['containers']

    # イメージの辞書
    images: dict[str, Image] = {}

    for container in init_containers + containers:
        logger.debug(f"{container['name']} @ {container['image']}")
        image_url = parse_image_url(container['image'])

        # イメージを pull
        image = get_puller(image_url.scheme)(image_url, driver)

        # イメージ名とオブジェクトのペアを保存
        images[container['image']] = image

    if networks:
        networks = networks.copy()
    else:
        try:
            # デフォルトネットワークを作成
            driver.create_network(default_network)
        except NetworkAlreadyExistsError:
            ...  # 既に存在するならよし
        networks = [default_network]

    # ボリュームがあれば作成
    volumes: dict[str, Volume] = {}
    for volume in manifest['spec'].get('volumes', []):
        if 'emptyDir' in volume:
            try:
                v = driver.get_volume(volume['name'])
            except VolumeNotFoundError:
                v = driver.create_volume(volume['name'])
            volumes[volume['name']] = v
        elif 'hostPath' in volume:
            volumes[volume['name']] = Volume(type='bind',
                                             source=volume['hostPath']['path'])

    restart_policy = manifest['spec'].get('restartPolicy', 'Always')

    parse_container = _ParseContainer(images, volumes, networks,
                                      restart_policy)

    # 既存の初期化コンテナを全て取得
    existing_init_containers = driver.get_init_containers()

    # 次の初期化コンテナを整理する
    next_init_containers = [parse_container(x, init=True)
                            for x in init_containers]

    logger.debug(f'既存の初期化コンテナ: {existing_init_containers}')
    logger.debug(f'次回の初期化コンテナ: {next_init_containers}')

    # 既存のコンテナを全て取得
    existing_containers = driver.get_containers()

    # 次のコンテナを整理する
    next_containers = [parse_container(x) for x in containers]

    logger.debug(f'既存のコンテナ: {existing_containers}')
    logger.debug(f'次回のコンテナ: {next_containers}')

    # 削除するコンテナと起動するコンテナを決定
    if existing_init_containers == next_init_containers:
        # 初期化コンテナに変更がなければ、定義差分から決定
        unnecessary_containers = _diff(existing_containers, next_containers)
        new_containers = _diff(next_containers, existing_containers)

        # 初期化コンテナ自体は変更がないので、削除も起動もしない
        unnecessary_init_containers = []
        new_init_containers = []

    else:
        # 初期化コンテナに変更があれば、全ての非初期化コンテナを削除し起動する
        unnecessary_containers = existing_containers
        new_containers = next_containers

        # 不要な初期化コンテナを決定
        unnecessary_init_containers = _diff(existing_init_containers,
                                            next_init_containers)

        # 起動する初期化コンテナを決定
        new_init_containers = _diff(next_init_containers,
                                    existing_init_containers)

    # 不要な初期化コンテナを削除
    logger.debug(f'削除する初期化コンテナ: {unnecessary_init_containers}')
    if unnecessary_init_containers:
        driver.remove_containers(
            x.name for x in unnecessary_init_containers
        )

    # 新しい初期化コンテナを起動
    logger.debug(f'起動する初期化コンテナ: {new_init_containers}')
    for container in new_init_containers:
        driver.run_init_container(container)

    # 不要なコンテナを削除
    logger.debug(f'削除するコンテナ: {unnecessary_containers}')
    if unnecessary_containers:
        driver.remove_containers(x.name for x in unnecessary_containers)

    # 新しいコンテナを起動
    logger.debug(f'起動するコンテナ: {new_containers}')
    for container in new_containers:
        driver.run_container(container)

    return ApplyResult(removed_init_containers=unnecessary_init_containers,
                       created_init_containers=new_init_containers,
                       removed_containers=unnecessary_containers,
                       created_containers=new_containers)

import logging.config
from dataclasses import dataclass
from typing import IO, Iterable, TypeVar

import yaml

from .drivers import (Container, Driver, EnvVar, Image,
                      NetworkAlreadyExistsError, Port, Volume,
                      VolumeNotFoundError)
from .pullers import get_puller
from .utils import package_name, parse_image_url

logger = logging.getLogger(package_name)

default_network = package_name

Self = TypeVar('Self', bound='Context')


@dataclass
class Context:
    driver: Driver
    file: IO[str]
    networks: list[str]


@dataclass
class ApplyResult:
    removed_init_containers: list[Container]
    created_init_containers: list[Container]
    removed_containers: list[Container]
    created_containers: list[Container]


def _merge_envs(*envs: Iterable[EnvVar]) -> list[EnvVar]:
    return [x for x in set(y for x in envs for y in x)]


def apply(ctx: Context) -> ApplyResult:
    logger.debug(f'Context: {ctx}')

    try:
        ctx.driver.install()
    except NotImplementedError:
        ...  # impl of install() is optional

    # マニフェストを読み込み、次の起動コンテナ情報を得る
    manifest = yaml.safe_load(ctx.file)

    init_containers = manifest['spec'].get('initContainers', [])
    containers = manifest['spec']['containers']

    # コンテナ名とイメージの辞書
    next_container_images: dict[str, Image] = {}

    for container in init_containers + containers:
        logger.debug(f"{container['name']} @ {container['image']}")
        image_url = parse_image_url(container['image'])

        # イメージを pull
        image = get_puller(image_url.scheme)(image_url, ctx.driver)

        # コンテナ名とイメージのペアを保存
        next_container_images[container['name']] = image

    if not ctx.networks:
        try:
            # デフォルトネットワークを作成
            ctx.driver.create_network(default_network)
        except NetworkAlreadyExistsError:
            ...  # 既に存在するならよし

        ctx.networks.append(default_network)

    # ボリュームがあれば作成
    volumes: dict[str, Volume] = {}
    for volume in manifest['spec'].get('volumes', []):
        if 'emptyDir' in volume:
            try:
                v = ctx.driver.get_volume(volume['name'])
            except VolumeNotFoundError:
                v = ctx.driver.create_volume(volume['name'])
            volumes[volume['name']] = v
        elif 'hostPath' in volume:
            volumes[volume['name']] = Volume(type='bind',
                                             source=volume['hostPath']['path'])

    base_restart_policy = manifest['spec'].get('restartPolicy', 'Always')

    def parse_container(container, init=False):
        container_name = container['name']
        image = next_container_images[container_name]
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

        if init and base_restart_policy == 'Always':
            # https://kubernetes.io/ja/docs/concepts/workloads/pods/init-containers/#detailed-behavior
            default_restart_policy = 'OnFailure'
        else:
            default_restart_policy = base_restart_policy
        # 本来 container.restartPolicy は、初期化コンテナのみ設定可能だが、非初期化コンテナも許容する
        # https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.30/#container-v1-core
        restart_policy = container.get('restartPolicy', default_restart_policy)

        networks = sorted(ctx.networks)

        mounts = []
        for mount in container.get('volumeMounts', []):
            volume = volumes[mount['name']]
            mounts.append(Volume(type=volume.type, source=volume.source,
                                 target=mount['mountPath']))
        mounts = sorted(mounts)

        return Container(name=container_name, image_id=image.id,
                         entrypoint=tuple(command), command=tuple(args),
                         environment=tuple(environment), ports=tuple(ports),
                         restart_policy=restart_policy,
                         networks=tuple(networks),
                         mounts=tuple(mounts))

    # 既存の初期化コンテナを全て取得
    existing_init_container_list = ctx.driver.get_init_containers()

    # 次の初期化コンテナを整理する
    next_init_container_list = [parse_container(x, init=True)
                                for x in init_containers]

    logger.debug(f'既存の初期化コンテナ: {existing_init_container_list}')
    logger.debug(f'次回の初期化コンテナ: {next_init_container_list}')

    # 既存のコンテナを全て取得
    existing_container_list = ctx.driver.get_containers()

    # 次のコンテナを整理する
    next_container_list = [parse_container(x) for x in containers]

    logger.debug(f'既存のコンテナ: {existing_container_list}')
    logger.debug(f'次回のコンテナ: {next_container_list}')

    # 削除するコンテナと起動するコンテナを決定
    existing_init_containers = set(existing_init_container_list)
    next_init_containers = set(next_init_container_list)

    if existing_init_containers == next_init_containers:
        # 初期化コンテナに変更がなければ、定義差分から決定
        existing_containers = set(existing_container_list)
        next_containers = set(next_container_list)
        unnecessary_containers = existing_containers - next_containers
        unnecessary_container_list = [x for x in existing_container_list
                                      if x in unnecessary_containers]
        new_containers = next_containers - existing_containers
        new_container_list = [x for x in next_container_list
                              if x in new_containers]

        # 初期化コンテナ自体は変更がないので、削除も起動もしない
        unnecessary_init_container_list = []
        new_init_container_list = []

    else:
        # 初期化コンテナに変更があれば、全ての非初期化コンテナを削除し起動する
        unnecessary_container_list = existing_container_list
        new_container_list = next_container_list

        # 不要な初期化コンテナを決定
        unnecessary_init_containers = \
            existing_init_containers - next_init_containers
        unnecessary_init_container_list = [
            x for x in existing_init_container_list
            if x in unnecessary_init_containers
        ]

        # 起動する初期化コンテナを決定
        new_init_containers = next_init_containers - existing_init_containers
        new_init_container_list = [x for x in next_init_container_list
                                   if x in new_init_containers]

    # 不要な初期化コンテナを削除
    logger.debug(f'削除する初期化コンテナ: {unnecessary_init_container_list}')
    if unnecessary_init_container_list:
        ctx.driver.remove_containers(
            x.name for x in unnecessary_init_container_list
        )

    # 新しい初期化コンテナを起動
    logger.debug(f'起動する初期化コンテナ: {new_init_container_list}')
    for container in new_init_container_list:
        ctx.driver.run_init_container(container)

    # 不要なコンテナを削除
    logger.debug(f'削除するコンテナ: {unnecessary_container_list}')
    if unnecessary_container_list:
        ctx.driver.remove_containers(x.name
                                     for x in unnecessary_container_list)

    # 新しいコンテナを起動
    logger.debug(f'起動するコンテナ: {new_container_list}')
    for container in new_container_list:
        ctx.driver.run_container(container)

    return ApplyResult(removed_init_containers=unnecessary_init_container_list,
                       created_init_containers=new_init_container_list,
                       removed_containers=unnecessary_container_list,
                       created_containers=new_container_list)

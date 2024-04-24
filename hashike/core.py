import logging.config
from dataclasses import dataclass
from typing import Iterable, TypeVar

import yaml

from .drivers import (Container, Driver, EnvVar, Image,
                      NetworkAlreadyExistsError, Port, Volume,
                      VolumeNotFoundError)
from .pullers import get_puller
from .utils import URL, open_url, package_name, parse_image_url

logger = logging.getLogger(package_name)

default_network = package_name

Self = TypeVar('Self', bound='Context')


@dataclass
class Context:
    driver: Driver
    file: URL
    networks: list[str]


@dataclass
class ApplyResult:
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
    with open_url(ctx.file, encoding='utf8') as f:
        manifest = yaml.safe_load(f)

    # コンテナ名とイメージの辞書
    next_container_images: dict[str, Image] = {}

    for container in manifest['spec']['containers']:
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

    # 既存のコンテナを全て取得
    existing_container_list = ctx.driver.get_all_managed_containers()

    # 次のコンテナを整理する
    next_container_list: list[Container] = []

    for next_container in manifest['spec']['containers']:
        container_name = next_container['name']
        image = next_container_images[container_name]
        command = next_container.get('command', image.entrypoint)
        args = next_container.get('args', image.command)

        ports = []
        for port in next_container.get('ports', []):
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
                                   for env in next_container.get('env', [])])
        environment = sorted(environment)

        restart_policy = next_container.get('restartPolicy', 'Always')

        networks = sorted(ctx.networks)

        mounts = []
        for mount in next_container.get('volumeMounts', []):
            volume = volumes[mount['name']]
            mounts.append(Volume(type=volume.type, source=volume.source,
                                 target=mount['mountPath']))
        mounts = sorted(mounts)

        next_container_list.append(Container(name=container_name,
                                             image_id=image.id,
                                             entrypoint=tuple(command),
                                             command=tuple(args),
                                             environment=tuple(environment),
                                             ports=tuple(ports),
                                             restart_policy=restart_policy,
                                             networks=tuple(networks),
                                             mounts=tuple(mounts)))

    logger.debug(f'既存のコンテナ: {existing_container_list}')
    logger.debug(f'次回のコンテナ: {next_container_list}')

    existing_containers = set(existing_container_list)
    next_containers = set(next_container_list)

    # 不要になったコンテナを削除
    unnecessary_containers = existing_containers - next_containers
    logger.debug(f'削除するコンテナ: {unnecessary_containers}')
    if unnecessary_containers:
        ctx.driver.remove_containers(x.name for x in unnecessary_containers)

    # 新しいコンテナを起動
    new_containers = next_containers - existing_containers
    logger.debug(f'起動するコンテナ: {new_containers}')
    for container in new_containers:
        ctx.driver.run_container(container)

    return ApplyResult(removed_containers=[x for x in existing_container_list
                                           if x in unnecessary_containers],
                       created_containers=[x for x in next_container_list
                                           if x in new_containers])

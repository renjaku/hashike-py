import json
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import IO, Optional

import docker.client
import docker.models
import docker.types

from ..utils import package_name
from .base import (Container, Driver, EnvVar, Image, InitContainerFailedError,
                   NetworkAlreadyExistsError, Port, Volume,
                   VolumeNotFoundError, driver, run_command)

label_key = package_name

restart_policy_bimap = {
    'Always': 'always',
    'always': 'Always',
    'OnFailure': 'on-failure',
    'on-failure': 'OnFailure'
}


@driver('docker')
@dataclass
class DockerDriver(Driver):
    client: docker.client.DockerClient = field(init=False)

    def __post_init__(self):
        self.client = docker.from_env()

    def _create_image(self, image: docker.models.images.Image):
        environment = tuple(sorted(
            EnvVar(*env.split('=', 1))
            for env in image.attrs['Config'].get('Env') or []
        ))
        entrypoint = tuple(image.attrs['Config'].get('Entrypoint') or [])
        command = tuple(image.attrs['Config'].get('Cmd') or [])
        return Image(id=image.id, references=tuple(image.attrs['RepoTags']),
                     environment=environment, entrypoint=entrypoint,
                     command=command)

    def get_images(self) -> list[Image]:
        return list(map(self._create_image, self.client.images.list()))

    def pull(self, image: str) -> Image:
        repo, tag = image.split(':', 1)
        self.client.images.pull(repo, tag)
        return self._create_image(self.client.images.get(image))

    def load_docker_archive(self, fileobj: IO[bytes]) -> None:
        self.client.images.load(fileobj.read())

    def create_network(self, network: str) -> None:
        if self.client.networks.list(network):
            raise NetworkAlreadyExistsError(network)

        self.client.networks.create(network, driver='bridge')

    def get_volume(self, volume: str) -> Volume:
        try:
            v = self.client.volumes.get(volume)
        except docker.errors.NotFound as e:
            raise VolumeNotFoundError from e

        return Volume(type='volume', source=v.name)

    def create_volume(self, volume: str):
        v = self.client.volumes.create(volume, labels={label_key: None})
        return Volume(type='volume', source=v.name)

    def _get_containers(self, init: bool = False) -> list[Container]:
        label = f"{label_key}={'init' if init else ''}"
        containers = self.client.containers.list(all=True,
                                                 filters=dict(label=label))

        results = []

        for container in containers:
            entrypoint = container.attrs['Config'].get('Entrypoint') or []
            command = container.attrs['Config'].get('Cmd') or []

            ports = []
            port_bindings = \
                container.attrs['HostConfig'].get('PortBindings') or {}
            for (container_port_protocol,
                 host_bindings) in port_bindings.items():
                port_s, protocol = container_port_protocol.split('/', 1)
                container_port = int(port_s)
                for host_binding in host_bindings or {}:
                    ports.append(Port(
                        container_port=container_port,
                        host_ip=host_binding.get('HostIp') or None,
                        host_port=int(host_binding['HostPort']),
                        protocol=protocol
                    ))
            ports = sorted(ports)

            environment = tuple(sorted(
                EnvVar(*x.split('=', 1))
                for x in container.attrs['Config'].get('Env') or []
            ))

            restart_policy = (
                container.attrs['HostConfig'].get('RestartPolicy') or {}
            ).get('Name', 'always')
            restart_policy = restart_policy_bimap[restart_policy]

            networks = tuple(sorted((
                container.attrs['NetworkSettings'].get('Networks') or {}
            ).keys()))

            mounts = tuple(sorted(
                Volume(type=x['Type'], source=x.get('Name', x['Source']),
                       target=x['Destination'])
                for x in container.attrs['Mounts']
            ))

            results.append(Container(name=container.name,
                                     image_id=container.image.id,
                                     entrypoint=tuple(entrypoint),
                                     command=tuple(command),
                                     environment=environment,
                                     ports=tuple(ports),
                                     restart_policy=restart_policy,
                                     networks=networks,
                                     mounts=mounts))

        return results

    def get_init_containers(self) -> list[Container]:
        return self._get_containers(init=True)

    def get_containers(self) -> list[Container]:
        return self._get_containers()

    def remove_containers(self, names: Iterable[str]) -> None:
        for name in names:
            container = self.client.containers.get(name)
            container.remove(force=True)

    def _run_container(
        self, container: Container, init: bool = False
    ) -> docker.models.containers.Container:
        run_opts = {}

        if container.networks:
            run_opts['network'] = container.networks[0]

        restart_policy = dict(
            Name=restart_policy_bimap[container.restart_policy]
        )

        mounts = [
            docker.types.Mount(type=x.type, source=x.source, target=x.target)
            for x in container.mounts
        ]

        raw_container = self.client.containers.run(
            container.image_id,
            name=container.name,
            labels={label_key: 'init'} if init else [label_key],
            restart_policy=restart_policy,
            detach=True,
            environment=[f'{k}={v}' for k, v in container.environment],
            ports={f'{x.container_port}/{x.protocol}': (x.host_ip, x.host_port)
                   for x in container.ports},
            entrypoint=list(container.entrypoint),
            command=list(container.command),
            mounts=mounts,
            **run_opts
        )

        if container.networks[1:]:
            networks = self.client.networks.list(names=container.networks[1:])
            for network in networks:
                network.connect(raw_container)

        return raw_container

    def run_init_container(self, container: Container) -> None:
        raw_container = self._run_container(container, init=True)

        if container.restart_policy == 'Always':
            ready = False
            n_healthy = 0
            for _ in range(60):
                raw_container.reload()  # 状態を更新
                if raw_container.status == 'running':
                    n_healthy += 1
                    if n_healthy == 4:
                        ready = True
                        break
                time.sleep(1)
            if not ready:
                raise InitContainerFailedError
        else:
            response = raw_container.wait()  # 終了を待機
            if response['StatusCode'] != 0:
                raise InitContainerFailedError

    def run_container(self, container: Container) -> None:
        self._run_container(container)


@driver('docker-cli')
@dataclass
class DockerCLIDriver(Driver):
    def _get_images(self, id_or_ref: Optional[str] = None):
        cmd = 'docker image ls --no-trunc --format "{{.ID}}"'

        if id_or_ref:
            cmd += ' ' + id_or_ref

        ids = set(run_command(cmd).stdout.strip().splitlines())

        proc = run_command(f"docker image inspect {' '.join(ids)}")
        details = json.loads(proc.stdout)

        for detail in details:
            id = detail['Id']
            refs = tuple(detail['RepoTags'])
            environment = tuple(sorted(
                EnvVar(*env.split('=', 1))
                for env in detail['Config'].get('Env') or []
            ))
            entrypoint = tuple(detail['Config'].get('Entrypoint') or [])
            command = tuple(detail['Config'].get('Cmd') or [])
            yield Image(id=id, references=refs, environment=environment,
                        entrypoint=entrypoint, command=command)

    def get_images(self) -> list[Image]:
        return list(self._get_images())

    def pull(self, image: str) -> Image:
        run_command(f'docker image pull {image}')
        return next(self._get_images(image))

    def load_docker_archive(self, fileobj: IO[bytes]) -> None:
        run_command('docker image load', input=fileobj.read())

    def create_network(self, network: str) -> None:
        try:
            run_command('docker network create --driver bridge ' + network)
        except subprocess.CalledProcessError as e:
            raise NetworkAlreadyExistsError from e  # ネットワーク重複エラーとみなす

    def get_volume(self, volume: str) -> Volume:
        try:
            proc = run_command('docker volume inspect ' + volume)
        except subprocess.CalledProcessError as e:
            raise VolumeNotFoundError from e  # 見つからないエラーとみなす

        return Volume(type='volume', source=json.loads(proc.stdout)[0]['Name'])

    def create_volume(self, volume: str) -> Volume:
        run_command(f'docker volume create --label={label_key} {volume}')
        return self.get_volume(volume)

    def _get_containers(self, init: bool = False) -> list[Container]:
        label = f"{label_key}={'init' if init else ''}"
        cmd = ('docker container ls --all --no-trunc '
               f'--filter "label={label}" '
               '--format "{{.ID}}"')

        ids = [x
               for x in run_command(cmd).stdout.strip().splitlines()
               if x.strip()]

        if not ids:
            return []

        proc = run_command('docker container inspect ' + ' '.join(ids))
        details = json.loads(proc.stdout)

        results = []

        for detail in details:
            name = detail['Name'].removeprefix('/')  # 内部的な名前の先頭には / が付く
            image_id = detail['Image']
            entrypoint = detail['Config'].get('Entrypoint') or []
            command = detail['Config'].get('Cmd') or []

            ports = []
            port_bindings = detail['HostConfig'].get('PortBindings') or {}
            for (container_port_protocol,
                 host_bindings) in port_bindings.items():
                port_s, protocol = container_port_protocol.split('/', 1)
                container_port = int(port_s)
                for host_binding in host_bindings or {}:
                    ports.append(Port(
                        container_port=container_port,
                        host_ip=host_binding.get('HostIp') or None,
                        host_port=int(host_binding['HostPort']),
                        protocol=protocol
                    ))
            ports = sorted(ports)

            environment = tuple(sorted(
                EnvVar(*env.split('=', 1))
                for env in detail['Config'].get('Env') or []
            ))

            restart_policy = (
                detail['HostConfig'].get('RestartPolicy') or {}
            ).get('Name', 'always')
            restart_policy = restart_policy_bimap[restart_policy]

            networks = tuple(sorted(
                (detail['NetworkSettings'].get('Networks') or {}).keys()
            ))

            mounts = tuple(sorted(
                Volume(type=x['Type'], source=x.get('Name', x['Source']),
                       target=x['Destination'])
                for x in detail['Mounts']
            ))

            results.append(Container(name=name, image_id=image_id,
                                     entrypoint=tuple(entrypoint),
                                     command=tuple(command),
                                     environment=environment,
                                     ports=tuple(ports),
                                     restart_policy=restart_policy,
                                     networks=networks,
                                     mounts=mounts))

        return results

    def get_init_containers(self) -> list[Container]:
        return self._get_containers(init=True)

    def get_containers(self) -> list[Container]:
        return self._get_containers()

    def remove_containers(self, names: Iterable[str]) -> None:
        run_command(f"docker container rm -f {' '.join(names)}")

    def _run_container(self, container: Container, init: bool = False) -> None:
        env_opts = (f'--env {k}={v}' for k, v in container.environment)
        entrypoint = (f'"{x}"' if ' ' in x else x
                      for x in container.entrypoint)
        command = (f'"{x}"' if ' ' in x else x for x in container.command)
        publish_opts = (
            f'--publish {x.host_port}:{x.container_port}/{x.protocol}'
            for x in container.ports
        )
        restart_policy = restart_policy_bimap[container.restart_policy]

        network_opt = ''
        if container.networks:
            network_opt = '--network ' + container.networks[0]

        mount_ops = (
            f'--mount type={x.type},source="{x.source}",target={x.target}'
            for x in container.mounts
        )

        run_command(f"""
docker container run
    --name {container.name}
    --label {f"{label_key}={'init' if init else ''}"}
    --restart {restart_policy}
    {network_opt}
    --detach
    {' '.join(env_opts)}
    --entrypoint {' '.join(entrypoint)}
    {' '.join(publish_opts)}
    {' '.join(mount_ops)}
    {container.image_id}
    {' '.join(command)}
""".replace('\n', ' ').strip())

        for network in container.networks[1:]:
            run_command(f'docker network connect {network} {container.name}')

    def run_init_container(self, container: Container) -> None:
        self._run_container(container)

        if container.restart_policy == 'Always':
            ready = False
            n_healthy = 0
            cmd = ('docker container inspect --format "{{json .State}}" '
                   f'{container.name}')
            for _ in range(60):
                proc = run_command(cmd)
                details = json.loads(proc.stdout)
                if details['Status'] == 'running':
                    n_healthy += 1
                    if n_healthy == 4:
                        ready = True
                        break
                time.sleep(1)
            if not ready:
                raise InitContainerFailedError
        else:
            cmd = 'docker container wait ' + container.name
            proc = run_command(cmd)  # 終了を待機
            if int(proc.stdout) != 0:
                raise InitContainerFailedError

    def run_container(self, container: Container) -> None:
        self._run_container(container)

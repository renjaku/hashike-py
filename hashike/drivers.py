import json
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import IO, Any, Literal, NamedTuple, Optional, Type, TypeVar, Union

import docker


class EnvVar(NamedTuple):
    name: str
    value: str


class Image(NamedTuple):
    id: str  # sha256: から始まるイメージ ID
    references: tuple[str, ...] = ()
    environment: tuple[EnvVar, ...] = ()
    entrypoint: tuple[str, ...] = ()
    command: tuple[str, ...] = ()


# https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.23/#containerport-v1-core
class Port(NamedTuple):
    container_port: int
    host_ip: Optional[str]
    host_port: int
    protocol: str = 'tcp'


class Container(NamedTuple):
    name: str
    image_id: str
    environment: tuple[EnvVar, ...] = ()
    entrypoint: tuple[str, ...] = ()
    command: tuple[str, ...] = ()
    ports: tuple[Port, ...] = ()
    restart_policy: Literal['Always', 'OnFailure'] = 'Always'
    networks: tuple[str, ...] = ()


class NetworkAlreadyExistsError(Exception):
    ...


Self = TypeVar('Self', bound='Driver')


@dataclass
class Driver(ABC):
    key: str

    def install(self: Self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_images(self: Self) -> list[Image]:
        ...

    @abstractmethod
    def pull(self: Self, image: str) -> Image:
        ...

    @abstractmethod
    def load_docker_archive(self: Self, fileobj: IO[bytes]) -> None:
        ...

    @abstractmethod
    def create_network(self: Self, network: str) -> None:
        ...

    @abstractmethod
    def get_all_managed_containers(self: Self) -> list[Container]:
        ...

    @abstractmethod
    def remove_containers(self: Self, names: Iterable[str]) -> None:
        ...

    @abstractmethod
    def run_container(self, container: Container):
        ...

    def __str__(self: Self):
        return self.key


_map: dict[str, Driver] = {}


def get_driver(key: str) -> Driver:
    return _map[key]


def driver(key: str):
    def wrap(cls: Type[Driver]):
        _map[key] = cls(key)
        return cls

    return wrap


restart_policy_bimap = {
    'Always': 'always',
    'always': 'Always',
    'OnFailure': 'on-failure',
    'on-failure': 'OnFailure'
}


@driver('docker')
class DockerDriver(Driver):
    client = docker.from_env()

    def _create_image(self, image: docker.models.images.Image):
        environment = tuple(sorted(
            EnvVar(*env.split('=', 1))
            for env in image.attrs['Config'].get('Env') or []
        ))
        entrypoint = image.attrs['Config'].get('Entrypoint')
        command = image.attrs['Config'].get('Cmd')
        return Image(id=image.id,
                     references=tuple(image.attrs['RepoTags']),
                     environment=environment,
                     entrypoint=tuple(entrypoint) if entrypoint else (),
                     command=tuple(command) if command else ())

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

    def get_all_managed_containers(self) -> list[Container]:
        containers = self.client.containers.list(all=True,
                                                 filters=dict(label='hashike'))

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
                EnvVar(*env.split('=', 1))
                for env in container.attrs['Config'].get('Env') or []
            ))

            restart_policy = (
                container.attrs['HostConfig'].get('RestartPolicy') or {}
            ).get('Name', 'always')
            restart_policy = restart_policy_bimap[restart_policy]

            networks = tuple(sorted((
                container.attrs['NetworkSettings'].get('Networks') or {}
            ).keys()))

            results.append(Container(name=container.name,
                                     image_id=container.image.id,
                                     entrypoint=tuple(entrypoint),
                                     command=tuple(command),
                                     environment=environment,
                                     ports=tuple(ports),
                                     restart_policy=restart_policy,
                                     networks=networks))

        return results

    def remove_containers(self, names: Iterable[str]) -> None:
        for name in names:
            container = self.client.containers.get(name)
            container.remove(force=True)

    def run_container(self, container: Container) -> None:
        run_opts = {}

        if container.networks:
            run_opts['network'] = container.networks[0]

        restart_policy = dict(
            Name=restart_policy_bimap[container.restart_policy]
        )

        raw_container = self.client.containers.run(
            container.image_id,
            name=container.name,
            labels=['hashike'],
            restart_policy=restart_policy,
            detach=True,
            environment=[f'{k}={v}' for k, v in container.environment],
            ports={f'{x.container_port}/{x.protocol}': (x.host_ip, x.host_port)
                   for x in container.ports},
            entrypoint=list(container.entrypoint),
            command=list(container.command),
            **run_opts
        )

        if container.networks[1:]:
            networks = self.client.networks.list(names=container.networks[1:])
            for network in networks:
                network.connect(raw_container)


def run_command(
    command: Union[str, list[str]], shell: bool = True,
    capture_output: bool = True, text: bool = True, check: bool = True,
    **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, shell=shell, capture_output=capture_output,
                          text=text, check=check, **kwargs)


@driver('docker-cli')
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
            refs = detail['RepoTags']
            environment = tuple(sorted(
                EnvVar(*env.split('=', 1))
                for env in detail['Config'].get('Env') or []
            ))
            entrypoint = detail['Config'].get('Entrypoint')
            command = detail['Config'].get('Cmd')
            yield Image(id, tuple(refs), environment,
                        tuple(entrypoint) if entrypoint else (),
                        tuple(command) if command else ())

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

    def get_all_managed_containers(self) -> list[Container]:
        cmd = ('docker container ls --all --no-trunc --filter "label=hashike" '
               '--format "{{.ID}}')

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

            results.append(Container(name=name, image_id=image_id,
                                     entrypoint=tuple(entrypoint),
                                     command=tuple(command),
                                     environment=environment,
                                     ports=tuple(ports),
                                     restart_policy=restart_policy,
                                     networks=networks))

        return results

    def remove_containers(self, names: Iterable[str]) -> None:
        run_command(f"docker container rm -f {' '.join(names)}")

    def run_container(self, container: Container) -> None:
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

        run_command(f"""
docker container run
    --name {container.name}
    --label hashike
    --restart {restart_policy}
    {network_opt}
    --detach
    {' '.join(env_opts)}
    --entrypoint {' '.join(entrypoint)}
    {' '.join(publish_opts)}
    {container.image_id}
    {' '.join(command)}
""".replace('\n', ' ').strip())

        for network in container.networks[1:]:
            run_command(f'docker network connect {network} {container.name}')

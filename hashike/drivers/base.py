import subprocess
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import IO, Any, Literal, NamedTuple, Optional, Type, TypeVar, Union


class EnvVar(NamedTuple):
    name: str
    value: str


class Image(NamedTuple):
    id: str  # sha256: から始まるイメージ ID
    references: tuple[str, ...] = ()
    environment: tuple[EnvVar, ...] = ()
    entrypoint: tuple[str, ...] = ()
    command: tuple[str, ...] = ()


# https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.30/#containerport-v1-core
class Port(NamedTuple):
    container_port: int
    host_ip: Optional[str]
    host_port: int
    protocol: str = 'tcp'


class Volume(NamedTuple):
    type: Literal['bind', 'volume']
    source: str
    target: Optional[str] = None


class Container(NamedTuple):
    name: str
    image_id: str
    environment: tuple[EnvVar, ...] = ()
    entrypoint: tuple[str, ...] = ()
    command: tuple[str, ...] = ()
    ports: tuple[Port, ...] = ()
    restart_policy: Literal['Always', 'OnFailure'] = 'Always'
    networks: tuple[str, ...] = ()
    mounts: tuple[Volume, ...] = ()


class NetworkAlreadyExistsError(Exception):
    ...


class VolumeNotFoundError(Exception):
    ...


class InitContainerFailedError(Exception):
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
    def get_volume(self: Self, volume: str) -> Volume:
        ...

    @abstractmethod
    def create_volume(self: Self, volume: str) -> Volume:
        ...

    @abstractmethod
    def get_init_containers(self: Self) -> list[Container]:
        ...

    @abstractmethod
    def get_containers(self: Self) -> list[Container]:
        ...

    @abstractmethod
    def remove_containers(self: Self, names: Iterable[str]) -> None:
        ...

    @abstractmethod
    def run_init_container(self: Self, container: Container) -> None:
        ...

    @abstractmethod
    def run_container(self: Self, container: Container):
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


def run_command(
    command: Union[str, list[str]], shell: bool = True,
    capture_output: bool = True, text: bool = True, check: bool = True,
    **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, shell=shell, capture_output=capture_output,
                          text=text, check=check, **kwargs)

# 艀 - Hashike

![Supported Python versions](https://img.shields.io/badge/python-%3E%3D3.9-%2334D058.svg)

Hashike runs, updates, and manages multiple containers

![Image](image.jpg)

## Quickstart

Install & apply:

```sh
pip install -U "hashike @ git+https://github.com/renjaku/hashike-py.git"
cat << EOF > my-manifest.yml
apiVersion: v1
kind: Hashike
metadata:
  namespace: my-project
  name: rest-api
spec:
  containers:
  - name: web
    image: nginx:alpine-slim
    env:
    - name: MY_ENV
      value: test
    ports:
      - containerPort: 80
        hostPort: 8000  # if omitted, it will be published in containerPort
        protocol: tcp
  - name: store
    image: redis:alpine
    ports:
      - containerPort: 6379
EOF
hashike apply my-manifest.yml
```

Multiple containers connected to the same network are started:

```sh
$ docker container ls --filter label=hashike --format "{{.ID}} {{.Names}} {{.Ports}} {{.Networks}}"
0123456789ab web 0.0.0.0:8000->80/tcp hashike
0123456789ac store 0.0.0.0:6379->6379/tcp hashike
```

## Object Storage + Docker Image Archive

Hashike allows you to launch containers from Docker image archives uploaded to object storage such as AWS S3.

Upload the `docker save` archive to S3:

```sh
docker save app:latest | gzip | \
  aws s3 cp --content-encoding gzip - s3://my-bucket/docker-archives/misc.images.tar.gz
```

`docker-archive+s3` scheme to specify the image:

```yml
apiVersion: v1
kind: Hashike
metadata:
  namespace: my-project
  name: my-service
spec:
  containers:
  - name: app
    image: docker-archive+s3://my-bucket/docker-archives/misc.images.tar.gz/app:latest
    ports:
      - containerPort: 8000
```

## Development

```sh
git clone https://github.com/renjaku/hashike-py.git hashike-py && cd $_
pip install -e .[dev]
```

If the following errors occur:

```txt
ERROR: File "setup.py" not found. Directory cannot be installed in editable mode: /path/to/repo
(A "pyproject.toml" file was found, but editable mode currently requires a setup.py based build.)
```

upgrade pip and retry:

```sh
pip install --upgrade pip
pip install -e .[dev]
```

Linting:

```sh
flake8 hashike/ && isort $_ && mypy $_
flake8 tests/ && isort $_ && mypy $_
```

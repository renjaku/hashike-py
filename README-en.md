# 艀 - Hashike

![Supported Python versions](https://img.shields.io/badge/python-%3E%3D3.9-%2334D058.svg)

Hashike runs, updates, and manages multiple containers

![Image](image.jpg)

## Overview

Hashike is designed for situations where serverless container services like AWS Fargate or function-as-a-service (FaaS) platforms like AWS Lambda are not available, and where setting up Kubernetes would be considered overkill.

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

Manifest files can also be read from stdin:

```sh
hashike apply - < my-manifest.yml
```

## Loading a Manifest File from an External Source

You can specify a manifest file located in an Amazon S3-compliant object storage:

```sh
hashike apply s3://my-bucket/my-manifest.yml
```

Using this, you can create a service that periodically updates containers:

```sh
# Create a systemd service
cat << EOF > /etc/systemd/system/update-containers.service
[Unit]
Description=Update Containers

[Service]
ExecStart=`which hashike` apply s3://my-bucket/my-manifest.yml
Type=oneshot
User=root

[Install]
WantedBy=multi-user.target
EOF

# Register and enable a systemd timer
cat << EOF > /etc/systemd/system/update-containers.timer
[Unit]
Description=Update Containers

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
Unit=update-containers.service

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now update-containers.timer
```

## Docker Image Archive + Amazon S3 Compliant Object Storage

You can launch containers from a Docker image archive uploaded to Amazon S3 compliant object storage.

Upload the archive created by `docker save` to S3:

```sh
docker save app:latest | gzip | \
  aws s3 cp --content-encoding gzip - s3://my-bucket/docker-archives/misc.images.tar.gz
```

Use the `docker-archive+s3` scheme to specify the image:

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

## Volume Mounting

Two types of volume mounts are available: `emptyDir` for ephemeral storage and `hostPath` for binding directories from the host.

Mounting `emptyDir` volumes:

```yml
apiVersion: v1
kind: Hashike
metadata:
  namespace: my-project
  name: rest-api
spec:
  containers:
  - name: web
    image: nginx:alpine-slim
    ports:
    - containerPort: 80
    volumeMounts:
    - name: nginx-templates
      mountPath: /etc/nginx/templates
  - name: store
    image: redis:alpine
    ports:
    - containerPort: 6379
    volumeMounts:
    - name: redis-data
      mountPath: /data
  volumes:
  - name: nginx-templates
    emptyDir: {}
  - name: redis-data
    emptyDir: {}
```

Mounting `hostPath` volumes:

```yml
apiVersion: v1
kind: Hashike
metadata:
  namespace: my-project
  name: rest-api
spec:
  containers:
  - name: web
    image: nginx:alpine-slim
    ports:
    - containerPort: 80
    volumeMounts:
    - name: nginx-templates
      mountPath: /etc/nginx/templates
  - name: store
    image: redis:alpine
    ports:
    - containerPort: 6379
    volumeMounts:
    - name: redis-data
      mountPath: /data
  volumes:
  - name: nginx-templates
    hostPath:
      path: /srv/web/nginx-templates
      type: Directory
  - name: redis-data
    hostPath:
      path: /srv/store/data
      type: Directory
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

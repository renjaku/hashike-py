# 艀 - Hashike

![Supported Python versions](https://img.shields.io/badge/python-%3E%3D3.9-%2334D058.svg)

Hashike は、複数のコンテナを起動、更新、管理します

## 概要

Hashike は、例えば AWS Fargate などのコンテナ向けサーバーレスであったり
AWS Lambda のような (所謂 FaaS) が使えない環境において
K8s を構築するのは過剰である、そんな状況下での利用を想定しています。

![Image](image.jpg)

## インストール

```sh
pip install "hashike @ git+https://github.com/renjaku/hashike-py.git"
```

もしエラーが発生した場合、[トラブルシューティング](#トラブルシューティング)を確認して下さい。

## クイックスタート

インストール & 起動:

```sh
pip install "hashike @ git+https://github.com/renjaku/hashike-py.git"
cat <<EOF > my-manifest.yml
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
      hostPort: 8000  # 省略した場合 containerPort で公開される
      protocol: tcp
  - name: store
    image: redis:alpine
    ports:
    - containerPort: 6379
EOF
hashike apply my-manifest.yml
```

同じネットワークに接続された複数のコンテナが起動します:

```sh
$ docker container ls --filter label=hashike --format "{{.ID}} {{.Names}} {{.Ports}} {{.Networks}}"
0123456789ab web 0.0.0.0:8000->80/tcp hashike
0123456789ac store 0.0.0.0:6379->6379/tcp hashike
```

マニフェストファイルは、標準入力から取り込むこともできます:

```sh
hashike apply - < my-manifest.yml
```

## 外部にあるマニフェストファイルをロードする

Amazon S3 準拠のオブジェクトストレージにあるマニフェストファイルを指定できます:

```sh
hashike apply s3://my-bucket/my-manifest.yml
```

これを利用して、定期的にコンテナを更新するサービスを作成できます。

```sh
# systemd サービスを作成
cat <<EOF > /etc/systemd/system/update-containers.service
[Unit]
Description=Update Containers

[Service]
ExecStart=`which hashike` apply s3://my-bucket/my-manifest.yml
Type=oneshot
User=root

[Install]
WantedBy=multi-user.target
EOF

# systemd タイマーを登録し、有効化
cat <<EOF > /etc/systemd/system/update-containers.timer
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

## Docker イメージアーカイブ + Amazon S3 準拠のオブジェクトストレージ

Amazon S3 準拠のオブジェクトストレージにアップロードした Docker イメージアーカイブから、コンテナを起動できます。

`docker save` 作成したアーカイブを S3 にアップロード:

```sh
docker save app:latest | gzip | \
  aws s3 cp --content-encoding gzip - s3://my-bucket/docker-archives/misc.images.tar.gz
```

`docker-archive+s3` スキームを使用してイメージを指定します:

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

## ボリュームマウント

通常のボリュームマウント `emptyDir` とホストへのバインドマウント `hostPath` の二種類が利用できます。

`emptyDir` ボリュームをマウント:

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

`hostPath` ボリュームをマウント:

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

## トラブルシューティング

### docker.errors.DockerException

```txt
docker.errors.DockerException: Error while fetching server API version: ('Connection aborted.', FileNotFoundError(2, 'No such file or directory'))
```

もしこのエラーが出た場合 Docker がインストールされていることを確認して下さい:

```sh
docker --version
```

### `pip install` 時のエラー

```sh
ERROR: After October 2020 you may experience errors when installing or updating packages. This is because pip will change the way that it resolves dependency conflicts.

We recommend you use --use-feature=2020-resolver to test your packages with the new resolver before it becomes the default.

botocore 1.34.94 requires urllib3<1.27,>=1.25.4; python_version < "3.10", but you'll have urllib3 2.2.1 which is incompatible.
```

もしこのエラーが出た場合 pip をアップグレードして、再試行して下さい:

```sh
pip install --upgrade pip
pip install "hashike @ git+https://github.com/renjaku/hashike-py.git"
```

## 開発

```sh
git clone https://github.com/renjaku/hashike-py.git hashike-py && cd $_
pip install -e .[dev]
```

もしこのエラーが出た場合:

```txt
ERROR: File "setup.py" not found. Directory cannot be installed in editable mode: /path/to/repo
(A "pyproject.toml" file was found, but editable mode currently requires a setup.py based build.)
```

pip をアップグレードして、再試行して下さい:

```sh
pip install --upgrade pip
pip install -e .[dev]
```

Lint を実行:

```sh
isort $_ && flake8 hashike/ && mypy $_
isort $_ && flake8 tests/ && mypy $_
```

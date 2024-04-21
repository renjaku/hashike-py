# 艀 - Hashike

![Supported Python versions](https://img.shields.io/badge/python-%3E%3D3.9-%2334D058.svg)

Hashike は、複数のコンテナを起動、更新、管理します

## 概要

Hashike は、例えば AWS Fargate などのコンテナ向けサーバーレスであったり
AWS Lambda のような (所謂 FaaS) が使えない環境において
K8s を構築するのは過剰である、そんな状況下での利用を想定しています。

![Image](image.jpg)

## クイックスタート

インストール & 起動:

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

pip をアップグレードして、再試行してください:

```sh
pip install --upgrade pip
pip install -e .[dev]
```

Lint を実行:

```sh
flake8 hashike/ && isort $_ && mypy $_
flake8 tests/ && isort $_ && mypy $_
```

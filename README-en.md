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
    image: nginx:latest
    env:
    - name: MY_ENV
      value: test
    ports:
      - containerPort: 80
        hostPort: 8000  # if omitted, it will be published in containerPort
        protocol: tcp
EOF
hashike apply my-manifest.yml
```

## Development

```sh
git clone https://github.com/renjaku/hashike-py.git hashike && cd $_
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

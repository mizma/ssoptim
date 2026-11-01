.DEFAULT_GOAL := build
.PHONY: build freeze publish package pubtest clean venv install test
PROJ_NAME = ssoptim
PY_VERSION = 3.12
SHELL = bash


build: venv
	@uv pip install --editable .

freeze:
	@uv pip freeze > requirements.txt

package: clean
	@uv build

publish: package
	@twine upload dist/*

pubtest: package
	@twine upload --repository pypitest dist/*

clean :
	@rm -rf dist build *.egg-info ssoptim/_version.py

venv:
	@uv venv --python $(PY_VERSION) .venv

install:
	@uv pip install -r requirements.txt

test:
	@uv run pytest -q

import os
import glob
from invoke import task

##############################################
### Setup default variables
##############################################

PY_VERSION = "3.12"

##############################################
### Helper Functions
##############################################


def run_rm(c, paths):
    """run rm -rf command equivalent for each of paths

    Args:
        c (Obj): invoke context object
        paths (List): List of paths to remove
    """
    # May not be necessary for *nix since rm command works on both files and
    # directories, but to keep consistency across platforms, use Python glob
    # to expand all wildcards.
    files = []
    for f in paths:
        files.extend(glob.glob(f))

    # run file removal function based on platform
    if os.name == "nt":
        for f in files:
            if os.path.isdir(f):
                c.run(f"rmdir /s /q {f}")
            else:
                c.run(f"del /f /q {f}")
    else:
        for f in files:
            c.run(f"rm -rf {f}")
    pass


##############################################
### Invoke Task Definitions
##############################################


@task()
def clean(c):
    """remove package artifacts"""
    run_rm(c, ["dist", "build", "*.egg-info", "ssoptim/_version.py"])
    pass


@task()
def venv(c):
    """initialize a uv-managed dev venv"""
    c.run(f"uv venv --python {PY_VERSION} .venv")
    pass


@task()
def freeze(c):
    """save requirements.txt"""
    c.run("uv pip freeze > requirements.txt")
    pass


@task(pre=[clean])
def package(c):
    """Generate sdist/wheel"""
    c.run("uv build")


@task(pre=[package])
def publish(c):
    """upload to PyPi"""
    c.run("twine upload dist/*")
    pass


@task(pre=[package])
def pubtest(c):
    """upload to pypitest"""
    c.run("twine upload --repository pypitest dist/*")
    pass


@task(pre=[freeze])
def install(c):
    """install package from requirements.txt"""
    c.run("uv pip install -r requirements.txt")


@task(pre=[venv])
def test(c):
    """run the pytest suite"""
    c.run("uv run pytest -q")


@task(pre=[venv], default=True)
def build(c):
    """Build and install as editable"""
    c.run("uv pip install --editable .")
    pass

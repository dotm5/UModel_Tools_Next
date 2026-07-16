#!/usr/bin/env python
import subprocess
import os
import sys
import time
import shutil
import argparse
import contextlib
import fnmatch
import typing as t

PYTHON_PATH = sys.executable


def print_error(*s: str):
    print(" ".join(s))


def print_success(*s: str):
    print(" ".join(s))


def print_info(*s: str):
    print(" ".join(s))


try:
    from pip import main as pipmain  # pylint: disable=unused-import, wrong-import-position
except ImportError:
    try:
        from pip._internal import main as pipmain  # pylint: disable=unused-import, wrong-import-position
    except ImportError:
        print_error("\npip is required to build this project.")
        sys.exit(1)


def _ignore_dev_dirs(directory: str, names: t.Iterable[str]) -> set[str]:
    """Ignore development-only directories and files during copytree."""
    _DEV_IGNORE = {
        ".git", ".github", ".idea", ".vscode", "__pycache__",
        "dist", "docs", "history", "reference", "scripts",
        "tests", "tests_blender", "tools",
        ".gitignore", "envi.png", "Envi_Wlbl.json",
        "blender_path.txt",
        "package_work",
    }
    ignored: set[str] = set()
    for name in names:
        if name in _DEV_IGNORE:
            ignored.add(name)
        elif name == "last_import_params.json":
            ignored.add(name)
        elif name.endswith(".pyc") or name.endswith(".pyo"):
            ignored.add(name)
        elif name.endswith(".umodel-cache.json"):
            ignored.add(name)
        elif name.lower().endswith(".zip"):
            ignored.add(name)
        elif fnmatch.fnmatchcase(name, "material_mapping_audit*.csv"):
            ignored.add(name)
    return ignored


@contextlib.contextmanager
def create_distribution(dist_path: t.Optional[str]):
    if dist_path:
        cwd = os.getcwd()
        try:
            print_info(f'\nCreating addon distribution in \"{dist_path}\" ...')
            _abs_dist = os.path.abspath(dist_path)
            shutil.rmtree(_abs_dist, ignore_errors=True)  # Start fresh every time.
            os.makedirs(_abs_dist, exist_ok=True)
            shutil.copytree(
                os.path.dirname(os.path.abspath(__file__)), _abs_dist,
                dirs_exist_ok=True,
                ignore=_ignore_dev_dirs,
            )
            print(os.path.dirname(os.path.abspath(__file__)), dist_path)
            os.chdir(_abs_dist)

            # Remove development-only directories that must not ship in the addon zip.
            _DEV_EXCLUDE_DIRS = (
                ".git",
                ".github",
                ".idea",
                ".vscode",
                "dist",
                "docs",
                "history",
                "reference",
                "scripts",
                "tests",
                "tests_blender",
                "tools",
            )
            _DEV_EXCLUDE_FILES = (
                ".gitignore",
                "blender_path.txt",
                "envi.png",
                "Envi_Wlbl.json",
                "last_import_params.json",
            )
            _DEV_EXCLUDE_GLOBS = (
                "*.zip",
                "*.pyc",
                "*.pyo",
                "*.umodel-cache.json",
                "material_mapping_audit*.csv",
            )

            for root, dirs, files in os.walk(_abs_dist, topdown=True):
                dirs_to_remove = [d for d in dirs if d in _DEV_EXCLUDE_DIRS]
                for subdir in dirs_to_remove:
                    shutil.rmtree(os.path.join(root, subdir), ignore_errors=True)
                    dirs.remove(subdir)

                if root == _abs_dist:
                    for filename in files:
                        if filename in _DEV_EXCLUDE_FILES:
                            os.remove(os.path.join(root, filename))
                        else:
                            for pattern in _DEV_EXCLUDE_GLOBS:
                                if fnmatch.fnmatchcase(filename, pattern):
                                    try:
                                        os.remove(os.path.join(root, filename))
                                    except OSError:
                                        pass

                for subdir in dirs:
                    if subdir == "__pycache__" or subdir.startswith(".") or subdir == "package_work":
                        shutil.rmtree(os.path.join(root, subdir), ignore_errors=True)

            yield None

        finally:
            os.chdir(cwd)
            print_success("\nSuccessfully created addon distribution.")
    else:
        yield None


def build_project(no_req: bool, dist_path: t.Optional[str]):
    start_time = time.time()

    print_info('\nBuilding UModel Tools Next...')
    print(f'Python third-party modules: {"OFF" if no_req else "ON"}')

    with create_distribution(dist_path):
        if not no_req:
            print_info('\nInstalling third-party Python modules...')

            with open('requirements.txt', encoding='utf-8', mode='r') as f:
                for line in f.readlines():
                    status = subprocess.call([PYTHON_PATH, '-m', 'pip', 'install', line, '-t',
                                             'umodel_tools/third_party', '--upgrade'])
                    if status:
                        print(f'\nError: failed installing module \"{line}\". See pip error above.')
                        sys.exit(1)

            prune_third_party('umodel_tools/third_party')

        else:
            print_info("Warning: Third-party Python modules will not be installed. (--noreq option)")

    print_success("UModel Tools Next building finished successfully.",
                  "Total build time: ", time.strftime("%M minutes %S seconds\a", time.gmtime(time.time() - start_time)))


def prune_third_party(third_party_dir: str):
    """Remove packaging metadata and CLI/test payloads that are not needed inside Blender."""
    if not os.path.isdir(third_party_dir):
        return

    for root, dirs, files in os.walk(third_party_dir, topdown=True):
        for subdir in list(dirs):
            if (
                subdir == 'tests'
                or subdir.endswith('.dist-info')
                or subdir == '__pycache__'
            ):
                shutil.rmtree(os.path.join(root, subdir), ignore_errors=True)
                dirs.remove(subdir)

        for filename in files:
            if filename.endswith(('.pyc', '.pyo')):
                try:
                    os.remove(os.path.join(root, filename))
                except OSError:
                    pass

    shutil.rmtree(os.path.join(third_party_dir, 'bin'), ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build UModel Tools Next."
                                                 "\n"
                                                 "\nRequired dependencies are:"
                                                 "\n  pip (https://pip.pypa.io/en/stable/installation/)",
                                     formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('--dist', type=str, help='create a distribution of WBS in specified directory')
    parser.add_argument('--noreq', action='store_true', help='do not pull python modules from PyPi')
    args = parser.parse_args()

    build_project(args.noreq, args.dist)

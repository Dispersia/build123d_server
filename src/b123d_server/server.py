import datetime
import importlib
import os
import pathlib
import sys
import time
import traceback
import types

# Prevent YACV from auto-starting a server on import
os.environ["YACV_DISABLE_SERVER"] = "1"

import click
from yacv_server import YACV

from b123d_server.reloader import Reloader


class Server:
    def __init__(
        self,
        model_file: pathlib.Path,
        poll_interval: float,
        excluded_dirs: list[pathlib.Path],
    ):
        if not model_file.exists():
            raise ValueError(f"Model file {model_file} does not exist")
        if not model_file.is_file():
            raise ValueError(f"Model path {model_file} is not a regular file")

        self.model_file = model_file.resolve()
        self.poll_interval = poll_interval

        # Ensure cwd and model dir are in the module search path
        cwd = str(pathlib.Path.cwd().resolve())
        if cwd not in sys.path:
            sys.path.insert(0, cwd)

        # Exclude stdlib dirs from file watching
        for prefix in {sys.prefix, sys.base_prefix}:
            platlibdir = (
                pathlib.Path(prefix)
                / sys.platlibdir
                / f"python{sys.version_info.major}.{sys.version_info.minor}"
            )
            if platlibdir.is_dir():
                excluded_dirs.append(platlibdir)

        self.reloader = Reloader([p.resolve() for p in excluded_dirs])

        self.last_files: set[pathlib.Path] | None = None
        self.last_updated: datetime.datetime | None = None
        self.last_error: list[str] | None = None

    def import_model_module(self) -> types.ModuleType | None:
        import_name = self.model_file.stem
        dir = self.model_file.parent
        while (dir / "__init__.py").is_file() and dir.parent != dir:
            import_name = f"{dir.name}.{import_name}"
            dir = dir.parent
        dir_str = str(dir)
        if dir_str not in sys.path:
            sys.path.insert(0, dir_str)

        importlib.invalidate_caches()
        try:
            model_module = importlib.import_module(import_name)
            self.last_files = self.reloader.find_files()
            self.last_updated = self.reloader.most_recent(self.last_files)
            self.last_error = None
            return model_module
        except Exception as e:
            self.last_files = None
            self.last_updated = None
            error = traceback.format_exception(e)
            if error != self.last_error:
                self.last_error = error
                print(f"Error importing {import_name}: {e}", file=sys.stderr)
                for line in error:
                    print(f"  {line}", end="", file=sys.stderr)
            return None

    def load_objects(self, model_module: types.ModuleType) -> dict[str, object] | None:
        try:
            objects = model_module.main()
            if not objects:
                print("No objects returned from main()")
                return None
            if isinstance(objects, dict):
                return objects
            elif isinstance(objects, list):
                return {f"part-{i + 1}": obj for i, obj in enumerate(objects)}
            else:
                return {"part": objects}
        except Exception as e:
            print(f"Error loading objects: {e}", file=sys.stderr)
            for line in traceback.format_exception(e):
                print(f"  {line}", end="", file=sys.stderr)
            return None

    def check_updated(self) -> bool:
        if not self.last_files or not self.last_updated:
            return True
        modtime = self.reloader.most_recent(self.last_files)
        return modtime != self.last_updated

    def reload(self) -> types.ModuleType | None:
        self.reloader.unload()
        return self.import_model_module()

    def serve(self):
        view_server = YACV()
        view_server.start()

        model_module = None
        first_load = True

        while True:
            try:
                updated = self.check_updated()

                if not model_module:
                    print(f"Loading {self.model_file}")
                    model_module = self.import_model_module()
                elif updated:
                    print(f"Change detected, reloading {self.model_file}")
                    model_module = self.reload()
                else:
                    time.sleep(self.poll_interval)
                    continue

                if not model_module:
                    time.sleep(self.poll_interval)
                    continue

                objects = self.load_objects(model_module)
                if not objects:
                    time.sleep(self.poll_interval)
                    continue

                if updated:
                    if not first_load:
                        view_server.clear()
                    first_load = False
                    view_server.show(
                        *objects.values(), names=list(objects.keys())
                    )

                time.sleep(self.poll_interval)

            except KeyboardInterrupt:
                print("\nExiting")
                sys.exit(0)


@click.command(no_args_is_help=True)
@click.argument(
    "model_file",
    type=click.Path(
        exists=True, dir_okay=False, file_okay=True, path_type=pathlib.Path
    ),
)
@click.option(
    "--port", "-p",
    type=click.IntRange(1, 65535),
    default=32323,
    show_default=True,
    help="Port to serve on",
)
@click.option(
    "--poll-interval", "-i",
    type=click.FloatRange(0.1, 5.0),
    default=1.0,
    show_default=True,
    help="Poll interval in seconds",
)
@click.option(
    "excluded_dirs",
    "--exclude-dir", "-x",
    type=click.Path(dir_okay=True, file_okay=False, path_type=pathlib.Path),
    multiple=True,
    default=[".venv", ".git"],
    show_default=True,
    help="Directories to exclude from watching",
)
def run(
    model_file: pathlib.Path,
    port: int,
    poll_interval: float,
    excluded_dirs: list[pathlib.Path],
):
    """Watch a build123d script for changes and display objects in the browser.

    MODEL_FILE should be a Python script with a main() function that returns
    build123d objects (a single object, a list, or a dict of name->object).
    """
    os.environ["YACV_HOST"] = "127.0.0.1"
    os.environ["YACV_PORT"] = str(port)
    print(f"Starting b123d-server on http://127.0.0.1:{port}")

    server = Server(
        model_file,
        poll_interval=poll_interval,
        excluded_dirs=list(excluded_dirs),
    )
    server.serve()


if __name__ == "__main__":
    run()

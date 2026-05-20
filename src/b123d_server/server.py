import datetime
import importlib
import os
import pathlib
import sys
import time
import traceback
import types

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

        cwd = str(pathlib.Path.cwd().resolve())
        if cwd not in sys.path:
            sys.path.insert(0, cwd)

        user_site = os.environ.get("B123D_USER_SITE")
        if user_site and user_site not in sys.path:
            sys.path.append(user_site)

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
        self.last_attempt_mtime: datetime.datetime | None = None

    @staticmethod
    def _top_error(e: Exception) -> str:
        lines = traceback.format_exception_only(type(e), e)
        return lines[-1].strip() if lines else str(e)

    def _report_error(self, message: str, e: Exception) -> None:
        error = traceback.format_exception(e)
        if error != self.last_error:
            self.last_error = error
            print(f"{message}: {e}", file=sys.stderr)
            for line in error:
                print(f"  {line}", end="", file=sys.stderr)
            print(f"ERROR:{self._top_error(e)}", flush=True)

    def import_model_module(self) -> types.ModuleType | None:
        import_name = self.model_file.stem
        dir = self.model_file.parent
        while (dir / "__init__.py").is_file() and dir.parent != dir:
            import_name = f"{dir.name}.{import_name}"
            dir = dir.parent
        dir_str = str(dir)
        if dir_str not in sys.path:
            sys.path.insert(0, dir_str)

        self.last_attempt_mtime = datetime.datetime.fromtimestamp(
            self.model_file.stat().st_mtime
        )
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
            self._report_error(f"Error importing {import_name}", e)
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
            self._report_error("Error loading objects", e)
            return None

    def check_updated(self) -> bool:
        if self.last_attempt_mtime is None:
            return True
        current = datetime.datetime.fromtimestamp(self.model_file.stat().st_mtime)
        if current != self.last_attempt_mtime:
            return True
        if self.last_files and self.last_updated:
            return self.reloader.most_recent(self.last_files) != self.last_updated
        return False

    def serve(self):
        view_server = YACV()
        view_server.start()

        first_show = True
        first_attempt = True

        while True:
            try:
                if not self.check_updated():
                    time.sleep(self.poll_interval)
                    continue

                if first_attempt:
                    print(f"Loading {self.model_file}")
                    first_attempt = False
                else:
                    print(f"Change detected, reloading {self.model_file}")
                    self.reloader.unload()

                model_module = self.import_model_module()
                if not model_module:
                    time.sleep(self.poll_interval)
                    continue

                objects = self.load_objects(model_module)
                if not objects:
                    time.sleep(self.poll_interval)
                    continue

                if not first_show:
                    view_server.clear()
                first_show = False
                view_server.show(*objects.values(), names=list(objects.keys()))
                print("OK", flush=True)

            except KeyboardInterrupt:
                print("\nExiting")
                sys.exit(0)
            except Exception as e:
                print(f"Unexpected server error: {e}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)

            time.sleep(self.poll_interval)


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

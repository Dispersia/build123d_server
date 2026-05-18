import datetime
import gc
import pathlib
import sys
import types


class Reloader:
    def __init__(self, ignore_dirs: list[pathlib.Path] | None = None):
        self.initial_modules = set(sys.modules.keys())
        self.ignore_paths = [
            pathlib.Path(path).resolve()
            for path in (ignore_dirs or [])
            if path.exists() and path.is_dir()
        ]

    def _filter_modules(self) -> dict[str, types.ModuleType]:
        filtered = {}
        for name, module in sys.modules.items():
            if name in self.initial_modules:
                continue
            file = getattr(module, "__file__", None)
            if not file:
                continue
            mod_file = pathlib.Path(file).resolve()
            if any(d in mod_file.parents for d in self.ignore_paths):
                continue
            filtered[name] = module
        return filtered

    def find_files(self) -> set[pathlib.Path]:
        modules = self._filter_modules()
        return {
            pathlib.Path(mod.__file__)
            for mod in modules.values()
            if mod.__file__ is not None
        }

    def most_recent(self, files: set[pathlib.Path]) -> datetime.datetime:
        return max(
            datetime.datetime.fromtimestamp(f.stat().st_mtime) for f in files
        )

    def unload(self) -> None:
        to_unload = self._filter_modules()
        for name in to_unload:
            del sys.modules[name]
        gc.collect()

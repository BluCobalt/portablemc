from sys import exit
import sys


if sys.version_info[0] < 3 or sys.version_info[1] < 6:
    print("PortableMC cannot be used with Python version prior to 3.6.x")
    exit(1)


from typing import cast, Dict, Set, Callable, Any, Optional, Generator, Tuple, List, Union
from argparse import ArgumentParser, Namespace
from urllib.error import HTTPError, URLError
from urllib import request as url_request
from json.decoder import JSONDecodeError
from datetime import datetime
from zipfile import ZipFile
from uuid import uuid4
from os import path
import subprocess
import platform
import hashlib
import atexit
import shutil
import time
import json
import re
import os


LAUNCHER_NAME = "portablemc"
LAUNCHER_VERSION = "1.1.0"
LAUNCHER_AUTHORS = "Théo Rozier"

VERSION_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
ASSET_BASE_URL = "https://resources.download.minecraft.net/{}/{}"
AUTHSERVER_URL = "https://authserver.mojang.com/{}"

JVM_EXEC_DEFAULT = "java"
JVM_ARGS_DEFAULT = "-Xmx2G -XX:+UnlockExperimentalVMOptions -XX:+UseG1GC -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 -XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M"

EXIT_VERSION_NOT_FOUND = 10
EXIT_CLIENT_JAR_NOT_FOUND = 11
EXIT_NATIVES_DIR_ALREADY_EXITS = 12
EXIT_DOWNLOAD_FILE_CORRUPTED = 13
EXIT_AUTHENTICATION_FAILED = 14
EXIT_VERSION_SEARCH_NOT_FOUND = 15
EXIT_DEPRECATED_ARGUMENT = 16
EXIT_LOGOUT_FAILED = 17
EXIT_URL_ERROR = 18

LOGGING_CONSOLE_REPLACEMENT = "<PatternLayout pattern=\"%d{HH:mm:ss.SSS} [%t] %-5level %logger{36} - %msg%n\"/>"


class PortableMC:

    def __init__(self):

        self._extensions: Dict[str, PortableExtension] = {}
        self._event_listeners: Dict[str, Set[Callable]] = {}
        self._main_dir: Optional[str] = None

        self._mc_os = self.get_minecraft_os()
        self._mc_arch = self.get_minecraft_arch()
        self._mc_archbits = self.get_minecraft_archbits()

        self._version_manifest: Optional[VersionManifest] = None
        self._auth_database: Optional[AuthDatabase] = None
        self._download_buffer: Optional[bytearray] = None

        self._messages = {

            "ext.missing_requirement.module": "Extension '{}' requires module '{}' to load.",
            "ext.missing_requirement.ext": "Extension '{}' requires another extension '{}' to load.",
            "ext.failed_to_build": "Failed to build extension '{}' (contact extension authors):",

            "args": "PortableMC is an easy to use portable Minecraft launcher in only one Python "
                    "script! This single-script launcher is still compatible with the official "
                    "(Mojang) Minecraft Launcher stored in .minecraft and use it.",
            "args.main_dir": "Set the main directory where libraries, assets, versions and binaries (at runtime) "
                             "are stored. It also contains the launcher authentication database.",
            "args.search": "Search for official Minecraft versions.",
            "args.start": "Start a Minecraft version, default to the latest release.",
            "args.start.dry": "Simulate game starting.",
            "args.start.demo": "Start game in demo mode.",
            "args.start.resol": "Set a custom start resolution (<width>x<height>).",
            "args.start.jvm": "Set a custom JVM 'javaw' executable path.",
            "args.start.jvm_args": "Change the default JVM arguments.",
            "args.start.work_dir": "Set the working directory where the game run and place for examples the "
                                   "saves (and resources for legacy versions).",
            "args.start.work_dir_bin": "Flag to force temporary binaries to be copied inside working directory, "
                                       "by default they are copied into main directory.",
            "args.start.no_better_logging": "Disable the better logging configuration built by the launcher in "
                                            "order to improve the log readability in the console.",
            "args.start.temp_login": "Flag used with -l (--login) to tell launcher not to cache your session if "
                                     "not already cached, deactivated by default.",
            "args.start.login": "Use a email or username (legacy) to authenticate using mojang servers (you "
                                "will be asked for password, it override --username and --uuid).",
            "args.start.username": "Set a custom user name to play.",
            "args.start.uuid": "Set a custom user UUID to play.",
            "args.login": "Login into your Mojang account, this will cache your tokens.",
            "args.logout": "Logout from your Mojang account.",
            "args.listext": "List extensions.",

            "abort": "=> Abort",
            "continue_using_main_dir": "Continue using this main directory? (y/N) ",

            "cmd.search.pending": "Searching for version '{}'...",
            "cmd.search.result": "=> {:10s} {:16s} {}",
            "cmd.search.not_found": "=> No version found",

            "cmd.logout.pending": "Logging out from {}...",
            "cmd.logout.success": "=> Logged out.",
            "cmd.logout.unknown_session": "=> This session is not cached.",

            "cmd.listext.title": "Extensions list ({}):",
            "cmd.listext.result": "=> {}, version: {}, authors: {}",

            "url_error.reason": "URL error: {}",

            "download.progress": "\rDownloading {}... {:6.2f}% {}/s {}",
            "download.of_total": "{:6.2f}% of total",
            "download.invalid_size": " => Invalid size",
            "download.invalid_sha1": " => Invalid SHA1",

            "auth.pending": "Authenticating {}...",
            "auth.already_cached": "=> Session already cached, validating...",
            "auth.refreshing": "=> Session failed to valid, refreshing...",
            "auth.refreshed": "=> Session refreshed.",
            "auth.error": "=> {}",
            "auth.validated": "=> Session validated.",
            "auth.caching": "=> Caching your session...",
            "auth.enter_your_password": "=> Enter {} password: ",
            "auth.logged_in": "=> Logged in",

            "version.resolving": "Resolving version {}",
            "version.found_cached": "=> Found cached metadata, loading...",
            "version.loaded": "=> Version loaded.",
            "version.failed_to_decode_cached": "=> Failed to decode cached metadata, try updating...",
            "version.found_in_manifest": "=> Found metadata in manifest, caching...",
            "version.not_found_in_manifest": "=> Not found in manifest.",
            "version.parent_version": "=> Parent version: {}",
            "version.parent_version_not_found": "=> Failed to find parent version {}",

            "start.welcome": "Welcome to PortableMC, the easy to use Python Minecraft Launcher.",
            "start.loading_version": "Loading {} {}...",
            "start.loading_jar_file": "Loading jar file...",
            "start.no_client_jar_file": "=> Can't find client download in version meta",
            "start.loading_assets": "Loading assets...",
            "start.failed_to_decode_asset_index": "=> Failed to decode assets index, try updating...",
            "start.found_asset_index": "=> Found asset index in metadata: {}",
            "start.legacy_assets": "=> This version use lagacy assets, put in {}",
            "start.virtual_assets": "=> This version use virtual assets, put in {}",
            "start.verifying_assets": "=> Verifying assets...",
            "start.loading_logger": "Loading logger config...",
            "start.generating_better_logging_config": "=> Generating better logging configuration...",
            "start.loading_libraries": "Loading libraries and natives...",
            "start.no_download_for_library": "=> Can't found any download for library {}",
            "start.cached_library_not_found": "=> Can't found cached library {} at {}",
            "start.dry": "Dry run, stopping.",
            "start.starting": "Starting game...",
            "start.extracting_natives": "=> Extracting natives...",
            "start.running": "Running...",
            "start.stopped": "Game stopped, clearing natives.",
            "start.run.session": "=> Username: {}, UUID: {}",
            "start.run.command_line": "=> Command line: {}"

        }

    def start(self):

        self._register_extensions()

        parser = self.register_arguments()
        args = parser.parse_args()
        subcommand = args.subcommand

        if subcommand is None:
            parser.print_help()
            return

        if "ignore_main_dir" not in args or not args.ignore_main_dir:
            self._main_dir = self.get_minecraft_dir() if args.main_dir is None else path.realpath(args.main_dir)
            if not path.isdir(self._main_dir):
                if self.prompt("continue_using_main_dir") != "y":
                    self.print("abort")
                    exit(0)
                os.makedirs(self._main_dir, 0o777, True)

        """self.trigger_event("subcommand", lambda: {
            "subcommand": subcommand,
            "args": args
        })"""

        exit(self.start_subcommand(subcommand, args))

    def start_subcommand(self, subcommand: str, args: Namespace) -> int:
        builtin_func_name = "cmd_{}".format(subcommand)
        if hasattr(self, builtin_func_name) and callable(getattr(self, builtin_func_name)):
            return getattr(self, builtin_func_name)(args)
        else:
            return 0

    def _register_extensions(self):

        # This method is not designed to be dynamically replaced, to mark this we keep the underscore.
        from importlib.machinery import SourceFileLoader
        import importlib.util

        ext_dir = path.join(path.dirname(__file__), "exts")
        if path.isdir(ext_dir):
            for raw_ext_file in os.listdir(ext_dir):
                ext_file = path.abspath(path.join(ext_dir, raw_ext_file))
                if path.isfile(ext_file) and ext_file.endswith(".py"):
                    ext_name = raw_ext_file[:-3]
                    module_spec = importlib.util.spec_from_file_location("__ext_main__", ext_file)
                    module_loader = cast(SourceFileLoader, module_spec.loader)
                    module = importlib.util.module_from_spec(module_spec)
                    module_loader.exec_module(module)
                    if PortableExtension.is_valid(module):
                        self._extensions[ext_name] = PortableExtension(module, ext_name)

        for ext in self._extensions.values():
            ext.build(self)

        for ext in self._extensions.values():
            ext.load()

    def register_arguments(self) -> ArgumentParser:

        parser = ArgumentParser(
            allow_abbrev=False,
            prog="portablemc",
            description=self.get_message("args")
        )

        # Main directory is placed here in order to know the path of the auth database.
        parser.add_argument("--main-dir", help=self.get_message("args.main_dir"), dest="main_dir")

        self.register_subcommands(parser.add_subparsers(
            title="subcommands",
            dest="subcommand"
        ))

        """self.trigger_event("register_arguments", lambda: {
            "parser": parser,
            "sub_parsers": sub_parsers,
            "builtins_parsers": {
                "search": search,
                "start": start,
                "login": login,
                "logout": logout
            }
        })"""

        return parser

    def register_subcommands(self, subcommands):
        self.register_search_arguments(subcommands.add_parser("search", help=self.get_message("args.search")))
        self.register_start_arguments(subcommands.add_parser("start", help=self.get_message("args.start")))
        self.register_login_arguments(subcommands.add_parser("login", help=self.get_message("args.login")))
        self.register_logout_arguments(subcommands.add_parser("logout", help=self.get_message("args.logout")))
        subcommands.add_parser("listext", help=self.get_message("args.listext"))

    def register_search_arguments(self, parser: ArgumentParser):
        parser.add_argument("input")
        parser.set_defaults(ignore_main_dir=True)

    def register_start_arguments(self, parser: ArgumentParser):
        parser.add_argument("--dry", help=self.get_message("args.start.dry"), default=False, action="store_true")
        parser.add_argument("--demo", help=self.get_message("args.start.demo"), default=False, action="store_true")
        parser.add_argument("--resol", help=self.get_message("args.start.resol"), type=self._decode_resolution, dest="resolution")
        parser.add_argument("--jvm", help=self.get_message("args.start.jvm"), default=JVM_EXEC_DEFAULT)
        parser.add_argument("--jvm-args", help=self.get_message("args.start.jvm_args"), default=JVM_ARGS_DEFAULT, dest="jvm_args")
        parser.add_argument("--work-dir", help=self.get_message("args.start.work_dir"), dest="work_dir")
        parser.add_argument("--work-dir-bin", help=self.get_message("args.start.work_dir_bin"), default=False, action="store_true", dest="work_dir_bin")
        parser.add_argument("--no-better-logging", help=self.get_message("args.start.no_better_logging"), default=False, action="store_true", dest="no_better_logging")
        parser.add_argument("-t", "--temp-login", help=self.get_message("args.start.temp_login"), default=False, action="store_true", dest="templogin")
        parser.add_argument("-l", "--login", help=self.get_message("args.start.login"))
        parser.add_argument("-u", "--username", help=self.get_message("args.start.username"))
        parser.add_argument("-i", "--uuid", help=self.get_message("args.start.uuid"))
        parser.add_argument("version", nargs="?", default="release")

    def register_login_arguments(self, parser: ArgumentParser):
        parser.add_argument("email_or_username")

    def register_logout_arguments(self, parser: ArgumentParser):
        parser.add_argument("email_or_username")

    # Builtin subcommands

    def cmd_search(self, args: Namespace) -> int:
        self.print("cmd.search.pending", args.input)
        manifest = self.get_version_manifest()
        found = False
        for version_data in manifest.search_versions(args.input):
            found = True
            self.print("cmd.search.result",
                       version_data["type"],
                       version_data["id"],
                       self.format_iso_date(version_data["releaseTime"]))
        if not found:
            self.print("cmd.search.not_found")
            return EXIT_VERSION_SEARCH_NOT_FOUND
        else:
            return 0

    def cmd_login(self, args: Namespace) -> int:
        entry = self.promp_password_and_authenticate(args.email_or_username, True)
        return EXIT_AUTHENTICATION_FAILED if entry is None else 0

    def cmd_logout(self, args: Namespace) -> int:
        email_or_username = args.email_or_username
        self.print("cmd.logout.pending", email_or_username)
        auth_db = self.get_auth_database()
        auth_db.load()
        entry = auth_db.get_entry(email_or_username)
        if entry is not None:
            entry.invalidate()
            auth_db.remove_entry(email_or_username)
            auth_db.save()
            self.print("cmd.logout.success")
            return 0
        else:
            self.print("cmd.logout.unknown_session")
            return EXIT_LOGOUT_FAILED

    def cmd_listext(self, _args: Namespace) -> int:
        self.print("cmd.listext.title", len(self._extensions))
        for ext in self._extensions.values():
            self.print("cmd.listext.result", ext.name, ext.version, ", ".join(ext.authors))
        return 0

    def cmd_start(self, args: Namespace) -> int:

        # Get all arguments
        work_dir = self._main_dir if args.main_dir is None else path.realpath(args.main_dir)
        uuid = None if args.uuid is None else args.uuid.replace("-", "")
        username = args.username

        # Login if needed
        if args.login is not None:
            auth_entry = self.promp_password_and_authenticate(args.login, not args.templogin)
            if auth_entry is None:
                return EXIT_AUTHENTICATION_FAILED
            uuid = auth_entry.uuid
            username = auth_entry.username
        else:
            auth_entry = None

        # Setup defaut UUID and/or username if needed
        if uuid is None: uuid = uuid4().hex
        if username is None: username = uuid[:8]

        # Decode resolution
        custom_resol = args.resolution  # type: Optional[Tuple[int, int]]
        if custom_resol is not None and len(custom_resol) != 2:
            custom_resol = None

        def jvm_args_modifier(jvm_args: List[str]):
            jvm_args.extend(args.jvm_args.split(" "))

        # Actual start
        try:
            self.start_game(
                work_dir=work_dir,
                dry_run=args.dry,
                uuid=uuid,
                username=username,
                version=args.version,
                no_better_logging=args.no_better_logging,
                work_dir_bin=args.work_dir_bin,
                resolution=custom_resol,
                demo=args.demo,
                jvm=args.jvm,
                auth_entry=auth_entry,
                jvm_args_modifier=jvm_args_modifier
            )
        except VersionNotFoundError:
            return EXIT_VERSION_NOT_FOUND
        except URLError as err:
            self.print("url_error.reason", err.reason)
            return EXIT_URL_ERROR
        except DownloadCorruptedError as err:
            self.print("download.{}".format(err.args[0]))
            return EXIT_DOWNLOAD_FILE_CORRUPTED

    # Generic start game method

    def start_game(self, *,
                   work_dir: str,
                   dry_run: bool,
                   uuid: str,
                   username: str,
                   version: str,
                   no_better_logging: bool,
                   work_dir_bin: bool,
                   resolution: Optional[Tuple[int, int]],
                   demo: bool,
                   jvm: str,
                   auth_entry: Optional["AuthEntry"],
                   version_meta_modifier: Optional[Callable[[dict], None]] = None,
                   libraries_modifier: Optional[Callable[[List[str], List[str]], None]] = None,
                   jvm_args_modifier: Optional[Callable[[List[str]], None]] = None,
                   final_args_modifier: Optional[Callable[[List[str]], None]] = None,
                   main_class_supplier: Union[None, Callable[[], str], str] = None,
                   args_replacement_modifier: Optional[Callable[[Dict[str, str]], None]] = None) -> None:

        # This method can raise these errors:
        # - VersionNotFoundError: if the given version was not found
        # - URLError: for any URL resolving error
        # - DownloadCorruptedError: if a download is corrupted

        self.print("start.welcome")

        """# Get all arguments
        work_dir = self._main_dir if args.main_dir is None else path.realpath(args.main_dir)
        dry_run = args.dry
        uuid = None if args.uuid is None else args.uuid.replace("-", "")
        username = args.username

        # Login if needed
        if args.login is not None:
            auth_entry = self.promp_password_and_authenticate(args.login, not args.templogin)
            if auth_entry is None:
                return EXIT_AUTHENTICATION_FAILED
            uuid = auth_entry.uuid
            username = auth_entry.username
        else:
            auth_entry = None

        # Setup defaut UUID and/or username if needed
        if uuid is None: uuid = uuid4().hex
        if username is None: username = uuid[:8]

        # Storage for extensions if they want to store values accros all events.
        ext_storage = {}
        self.trigger_event("start:setup", lambda: {
            "args": args,
            "work_dir": work_dir,
            "dry_run": dry_run,
            "uuid": uuid,
            "username": username,
            "storage": ext_storage
        })"""

        # Resolve version metadata
        """try:
            version, version_alias = self.get_version_manifest().filter_latest(version)
            version_meta, version_dir = self.resolve_version_meta_recursive(version)
        except VersionNotFoundError:
            raise AbordStartError(EXIT_VERSION_NOT_FOUND)
        except URLError as err:
            self.print("url_error.reason", err.reason)
            raise AbordStartError(EXIT_URL_ERROR)"""

        version, version_alias = self.get_version_manifest().filter_latest(version)
        version_meta, version_dir = self.resolve_version_meta_recursive(version)

        # Starting version dependencies resolving
        version_type = version_meta["type"]
        self.print("start.loading_version", version_type, version)

        if callable(version_meta_modifier):
            version_meta_modifier(version_meta)

        """self.trigger_event("start:version", lambda: {
            "version": version,
            "type": version_type,
            "meta": version_meta,
            "dir": version_dir,
            "storage": ext_storage
        })"""

        # JAR file loading
        self.print("start.loading_jar_file")
        version_jar_file = path.join(version_dir, "{}.jar".format(version))
        if not path.isfile(version_jar_file):
            version_downloads = version_meta["downloads"]
            if "client" not in version_downloads:
                self.print("start.no_client_jar_file")
                raise VersionNotFoundError()
            download_entry = DownloadEntry.from_version_meta_info(version_downloads["client"], version_jar_file, name="{}.jar".format(version))
            self.download_file_pretty(download_entry)

        """self.trigger_event("start:version_jar_file", lambda: {
            "file": version_jar_file,
            "storage": ext_storage
        })"""

        # Assets loading
        self.print("start.loading_assets")
        assets_dir = path.join(self._main_dir, "assets")
        assets_indexes_dir = path.join(assets_dir, "indexes")
        assets_index_version = version_meta["assets"]
        assets_index_file = path.join(assets_indexes_dir, "{}.json".format(assets_index_version))
        assets_index = None

        if path.isfile(assets_index_file):
            with open(assets_index_file, "rb") as assets_index_fp:
                try:
                    assets_index = json.load(assets_index_fp)
                except JSONDecodeError:
                    self.print("start.failed_to_decode_asset_index")

        if assets_index is None:
            asset_index_info = version_meta["assetIndex"]
            asset_index_url = asset_index_info["url"]
            self.print("start.found_asset_index", asset_index_url)
            assets_index = self.read_url_json(asset_index_url)
            if not path.isdir(assets_indexes_dir):
                os.makedirs(assets_indexes_dir, 0o777, True)
            with open(assets_index_file, "wt") as assets_index_fp:
                json.dump(assets_index, assets_index_fp)

        assets_objects_dir = path.join(assets_dir, "objects")
        assets_total_size = version_meta["assetIndex"]["totalSize"]
        assets_current_size = 0
        assets_virtual_dir = path.join(assets_dir, "virtual", assets_index_version)
        assets_mapped_to_resources = assets_index.get("map_to_resources", False)  # For version <= 13w23b
        assets_virtual = assets_index.get("virtual", False)  # For 13w23b < version <= 13w48b (1.7.2)

        if assets_mapped_to_resources:
            self.print("start.legacy_assets", path.join(work_dir, "resources"))
        if assets_virtual:
            self.print("start.virtual_assets", assets_virtual_dir)

        self.print("start.verifying_assets")
        for asset_id, asset_obj in assets_index["objects"].items():

            asset_hash = asset_obj["hash"]
            asset_hash_prefix = asset_hash[:2]
            asset_size = asset_obj["size"]
            asset_hash_dir = path.join(assets_objects_dir, asset_hash_prefix)
            asset_file = path.join(asset_hash_dir, asset_hash)

            if not path.isfile(asset_file) or path.getsize(asset_file) != asset_size:
                os.makedirs(asset_hash_dir, 0o777, True)
                asset_url = ASSET_BASE_URL.format(asset_hash_prefix, asset_hash)
                download_entry = DownloadEntry(asset_url, asset_size, asset_hash, asset_file, name=asset_id)
                self.download_file_pretty(download_entry,
                                          start_size=assets_current_size,
                                          total_size=assets_total_size)
            else:
                assets_current_size += asset_size

            if assets_mapped_to_resources:
                resources_asset_file = path.join(work_dir, "resources", asset_id)
                if not path.isfile(resources_asset_file):
                    os.makedirs(path.dirname(resources_asset_file), 0o777, True)
                    shutil.copyfile(asset_file, resources_asset_file)

            if assets_virtual:
                virtual_asset_file = path.join(assets_virtual_dir, asset_id)
                if not path.isfile(virtual_asset_file):
                    os.makedirs(path.dirname(virtual_asset_file), 0o777, True)
                    shutil.copyfile(asset_file, virtual_asset_file)

        # Logging configuration
        self.print("start.loading_logger")
        logging_arg = None
        if "logging" in version_meta:
            version_logging = version_meta["logging"]
            if "client" in version_logging:
                log_config_dir = path.join(assets_dir, "log_configs")
                os.makedirs(log_config_dir, 0o777, True)
                client_logging = version_logging["client"]
                logging_file_info = client_logging["file"]
                logging_file = path.join(log_config_dir, logging_file_info["id"])
                logging_dirty = False
                download_entry = DownloadEntry.from_version_meta_info(logging_file_info, logging_file, name=logging_file_info["id"])
                if not path.isfile(logging_file) or path.getsize(logging_file) != download_entry.size:
                    self.download_file_pretty(download_entry)
                    logging_dirty = True
                if not no_better_logging:
                    better_logging_file = path.join(log_config_dir, "portablemc-{}".format(logging_file_info["id"]))
                    if logging_dirty or not path.isfile(better_logging_file):
                        self.print("start.generating_better_logging_config")
                        with open(logging_file, "rt") as logging_fp:
                            with open(better_logging_file, "wt") as custom_logging_fp:
                                raw = logging_fp.read()\
                                    .replace("<XMLLayout />", LOGGING_CONSOLE_REPLACEMENT)\
                                    .replace("<LegacyXMLLayout />", LOGGING_CONSOLE_REPLACEMENT)
                                custom_logging_fp.write(raw)
                    logging_file = better_logging_file
                logging_arg = client_logging["argument"].replace("${path}", logging_file)

        # Libraries and natives loading
        self.print("start.loading_libraries")
        libraries_dir = path.join(self._main_dir, "libraries")
        classpath_libs = [version_jar_file]
        native_libs = []

        for lib_obj in version_meta["libraries"]:

            if "rules" in lib_obj:
                if not self.interpret_rule(lib_obj["rules"]):
                    continue

            lib_name = lib_obj["name"]  # type: str
            lib_type = None  # type: Optional[str]

            if "downloads" in lib_obj:

                lib_dl = lib_obj["downloads"]
                lib_dl_info = None

                if "natives" in lib_obj and "classifiers" in lib_dl:
                    lib_natives = lib_obj["natives"]
                    if self._mc_os in lib_natives:
                        lib_native_classifier = lib_natives[self._mc_os]
                        if self._mc_archbits is not None:
                            lib_native_classifier = lib_native_classifier.replace("${arch}", self._mc_archbits)
                        lib_name += ":{}".format(lib_native_classifier)
                        lib_dl_info = lib_dl["classifiers"][lib_native_classifier]
                        lib_type = "native"
                elif "artifact" in lib_dl:
                    lib_dl_info = lib_dl["artifact"]
                    lib_type = "classpath"

                if lib_dl_info is None:
                    self.print("start.no_download_for_library", lib_name)
                    continue

                lib_path = path.join(libraries_dir, lib_dl_info["path"])
                lib_dir = path.dirname(lib_path)

                os.makedirs(lib_dir, 0o777, True)
                download_entry = DownloadEntry.from_version_meta_info(lib_dl_info, lib_path, name=lib_name)

                if not path.isfile(lib_path) or path.getsize(lib_path) != download_entry.size:
                    self.download_file_pretty(download_entry)

            else:

                # If no 'downloads' trying to parse the maven dependency string "<group>:<product>:<version>
                # to directory path. This may be used by custom configuration that do not provide download
                # links like Optifine.

                lib_name_parts = lib_name.split(":")
                lib_path = path.join(libraries_dir, *lib_name_parts[0].split("."), lib_name_parts[1],
                                     lib_name_parts[2], "{}-{}.jar".format(lib_name_parts[1], lib_name_parts[2]))
                lib_type = "classpath"

                if not path.isfile(lib_path):
                    self.print("start.cached_library_not_found", lib_name, lib_path)
                    continue

            if lib_type == "classpath":
                classpath_libs.append(lib_path)
            elif lib_type == "native":
                native_libs.append(lib_path)

        if callable(libraries_modifier):
            libraries_modifier(classpath_libs, native_libs)

        """self.trigger_event("start:libraries", lambda: {
            "dir": libraries_dir,
            "classpath_libs": classpath_libs,
            "native_libs": native_libs,
            "storage": ext_storage
        })"""

        # Don't run if dry run
        if dry_run:
            self.print("start.dry")
            return

        # Start game
        self.print("start.starting")

        # Extracting binaries
        bin_dir = path.join(work_dir if work_dir_bin else self._main_dir, "bin", str(uuid4()))

        @atexit.register
        def _bin_dir_cleanup():
            if path.isdir(bin_dir):
                shutil.rmtree(bin_dir)

        self.print("start.extracting_natives")
        for native_lib in native_libs:
            with ZipFile(native_lib, 'r') as native_zip:
                for native_zip_info in native_zip.infolist():
                    if self.can_extract_native(native_zip_info.filename):
                        native_zip.extract(native_zip_info, bin_dir)

        """# Decode arguments
        custom_resol = args.resolution
        if custom_resol is not None and len(custom_resol) != 2:
            custom_resol = None"""

        features = {
            "is_demo_user": demo,
            "has_custom_resolution": resolution is not None
        }

        legacy_args = version_meta.get("minecraftArguments")

        raw_args = []
        raw_args.extend(self.interpret_args(version_meta["arguments"]["jvm"] if legacy_args is None else LEGACY_JVM_ARGUMENTS, features))
        #raw_args.extend(args.jvm_args.split(" "))

        if logging_arg is not None:
            raw_args.append(logging_arg)

        main_class = version_meta["mainClass"]
        if main_class == "net.minecraft.launchwrapper.Launch":
            raw_args.append("-Dminecraft.client.jar={}".format(version_jar_file))

        if callable(jvm_args_modifier):
            jvm_args_modifier(raw_args)

        if callable(main_class_supplier):
            main_class = main_class_supplier()
        elif isinstance(main_class_supplier, str):
            main_class = main_class_supplier

        """event_data = {
            "main_class": main_class,
            "args": raw_args,
            "storage": ext_storage
        }
        self.trigger_event("start:args_jvm", event_data)
        main_class = event_data["main_class"]"""

        raw_args.append(main_class)
        raw_args.extend(self.interpret_args(version_meta["arguments"]["game"], features) if legacy_args is None else legacy_args.split(" "))

        if callable(final_args_modifier):
            final_args_modifier(raw_args)

        """self.trigger_event("start:args_game", lambda: {
            "args": raw_args,
            "storage": ext_storage
        })"""

        # Arguments replacements
        start_args_replacements = {
            # Game
            "auth_player_name": username,
            "version_name": version,
            "game_directory": work_dir,
            "assets_root": assets_dir,
            "assets_index_name": assets_index_version,
            "auth_uuid": uuid,
            "auth_access_token": "" if auth_entry is None else auth_entry.format_token_argument(False),
            "user_type": "mojang",
            "version_type": version_type,
            # Game (legacy)
            "auth_session": "notok" if auth_entry is None else auth_entry.format_token_argument(True),
            "game_assets": assets_virtual_dir,
            "user_properties": "{}",
            # JVM
            "natives_directory": bin_dir,
            "launcher_name": LAUNCHER_NAME,
            "launcher_version": LAUNCHER_VERSION,
            "classpath": self.get_classpath_separator().join(classpath_libs)
        }

        if resolution is not None:
            start_args_replacements["resolution_width"] = str(resolution[0])
            start_args_replacements["resolution_height"] = str(resolution[1])

        if callable(args_replacement_modifier):
            args_replacement_modifier(start_args_replacements)

        """self.trigger_event("start:args_replacements", lambda: {
            "replacements": start_args_replacements,
            "storage": ext_storage
        })"""

        start_args = [jvm]
        for arg in raw_args:
            for repl_id, repl_val in start_args_replacements.items():
                arg = arg.replace("${{{}}}".format(repl_id), repl_val)
            start_args.append(arg)

        self.print("start.running")
        os.makedirs(work_dir, 0o777, True)
        self.run_game(start_args, work_dir, {
            "username": username,
            "uuid": uuid,
            "version": version,
            "args": start_args
        })

        self.print("start.stopped")

    def run_game(self, proc_args: list, proc_cwd: str, options: dict):
        self.print("", "====================================================")
        self.print("start.run.session", options["username"], options["uuid"])
        self.print("start.run.command_line", " ".join(options["args"]))
        subprocess.run(proc_args, cwd=proc_cwd)
        self.print("", "====================================================")

    # Getters

    def get_main_dir(self) -> str:
        return self._main_dir

    def get_version_manifest(self) -> 'VersionManifest':
        if self._version_manifest is None:
            self._version_manifest = VersionManifest.load_from_url()
        return self._version_manifest

    def get_auth_database(self) -> 'AuthDatabase':
        if self._auth_database is None:
            self._auth_database = AuthDatabase(path.join(self._main_dir, "portablemc_tokens"))
        return self._auth_database

    def get_download_buffer(self) -> bytearray:
        if self._download_buffer is None:
            self._download_buffer = bytearray(32768)
        return self._download_buffer

    def get_extensions(self) -> Dict[str, 'PortableExtension']:
        return self._extensions

    def get_extension(self, name: str) -> Optional['PortableExtension']:
        return self._extensions.get(name)

    def get_messages(self) -> Dict[str, str]:
        return self._messages

    def add_message(self, key: str, value: str):
        self._messages[key] = value

    """# Event listeners

    def add_event_listener(self, event: str, listener: Callable):
        listeners = self._event_listeners.get(event)
        if listeners is None:
            listeners = self._event_listeners[event] = set()
        listeners.add(listener)

    def remove_event_listener(self, event: str, listener: Callable):
        listeners = self._event_listeners.get(event)
        if listeners is not None:
            try:
                listeners.remove(listener)
            except KeyError:
                pass

    def trigger_event(self, event: str, data: Union[dict, Callable[[], dict]]):
        listeners = self._event_listeners.get(event)
        if listeners is not None:
            if callable(data):
                data = data()
            for listener in listeners:
                listener(data)"""

    # Public methods to be replaced by extensions

    def print(self, message_key: str, *args, traceback: bool = False, end: str = "\n"):
        print(self.get_message(message_key, *args), end=end)
        if traceback:
            import traceback
            traceback.print_exc()

    def prompt(self, message_key: str, *args, password: bool = False) -> str:
        print(self.get_message(message_key, *args), end="")
        if password:
            import getpass
            return getpass.getpass("")
        else:
            return input("")

    def get_message(self, message_key: str, *args) -> str:
        if not len(message_key):
            return args[0]
        msg = self._messages.get(message_key, message_key)
        try:
            return msg.format(*args)
        except IndexError:
            return msg

    def mixin(self, target: str, func):
        old_func = getattr(self, target, None)
        def wrapper(*args, **kwargs):
            return func(old_func, *args, **kwargs)
        setattr(self, target, wrapper)

    # Authentication

    def promp_password_and_authenticate(self, email_or_username: str, cache_in_db: bool) -> Optional['AuthEntry']:

        self.print("auth.pending", email_or_username)

        auth_db = self.get_auth_database()
        auth_db.load()

        auth_entry = auth_db.get_entry(email_or_username)
        if auth_entry is not None:
            self.print("auth.already_cached")
            if not auth_entry.validate():
                self.print("auth.refreshing")
                try:
                    auth_entry.refresh()
                    auth_db.save()
                    self.print("auth.refreshed")
                    return auth_entry
                except AuthError as auth_err:
                    self.print("auth.error", auth_err)
            else:
                self.print("auth.validated")
                return auth_entry

        try:
            password = self.prompt("auth.enter_your_password", password=True)
            auth_entry = AuthEntry.authenticate(email_or_username, password)
            if cache_in_db:
                self.print("auth.caching")
                auth_db.add_entry(email_or_username, auth_entry)
                auth_db.save()
            self.print("auth.logged_in")
            return auth_entry
        except AuthError as auth_err:
            self.print("auth.error", auth_err)
            return None

    # Version metadata

    def resolve_version_meta(self, name: str) -> Tuple[dict, str]:

        version_dir = path.join(self._main_dir, "versions", name)
        version_meta_file = path.join(version_dir, "{}.json".format(name))
        content = None

        self.print("version.resolving", name)

        if path.isfile(version_meta_file):
            self.print("version.found_cached")
            with open(version_meta_file, "rb") as version_meta_fp:
                try:
                    content = json.load(version_meta_fp)
                    self.print("version.loaded")
                except JSONDecodeError:
                    self.print("version.failed_to_decode_cached")

        if content is None:
            version_data = self.get_version_manifest().get_version(name)
            if version_data is not None:
                version_url = version_data["url"]
                self.print("version.found_in_manifest")
                content = self.read_url_json(version_url)
                os.makedirs(version_dir, 0o777, True)
                with open(version_meta_file, "wt") as version_meta_fp:
                    json.dump(content, version_meta_fp, indent=2)
            else:
                self.print("version.not_found_in_manifest")
                raise VersionNotFoundError(name)

        return content, version_dir

    def resolve_version_meta_recursive(self, name: str) -> Tuple[dict, str]:
        version_meta, version_dir = self.resolve_version_meta(name)
        while "inheritsFrom" in version_meta:
            self.print("version.parent_version", version_meta["inheritsFrom"])
            parent_meta, _ = self.resolve_version_meta(version_meta["inheritsFrom"])
            if parent_meta is None:
                self.print("version.parent_version_not_found", version_meta["inheritsFrom"])
                raise VersionNotFoundError(version_meta["inheritsFrom"])
            del version_meta["inheritsFrom"]
            self.dict_merge(parent_meta, version_meta)
            version_meta = parent_meta
        return version_meta, version_dir

    # Downloading

    def download_file_pretty(self,
                             entry: 'DownloadEntry', *,
                             start_size: int = 0,
                             total_size: int = 0) -> int:

        start_time = time.perf_counter()

        def progress_callback(p_dl_size: int, p_size: int, p_dl_total_size: int, p_total_size: int):
            nonlocal start_time
            of_total = self.get_message("download.of_total", p_dl_total_size / p_total_size * 100) if p_total_size != 0 else ""
            speed = self.format_bytes(p_dl_size / (time.perf_counter() - start_time))
            self.print("download.progress", entry.name, p_dl_size / p_size * 100, speed, of_total, end="")

        res = self.download_file(entry, start_size=start_size, total_size=total_size, progress_callback=progress_callback)
        self.print("", "")
        return res

    def download_file(self,
                      entry: 'DownloadEntry', *,
                      start_size: int = 0,
                      total_size: int = 0,
                      progress_callback: Optional[Callable[[int, int, int, int], None]] = None) -> int:

        with url_request.urlopen(entry.url) as req:
            with open(entry.dst, "wb") as dst_fp:

                dl_sha1 = hashlib.sha1()
                dl_size = 0

                buffer = self.get_download_buffer()

                while True:

                    read_len = req.readinto(buffer)
                    if not read_len:
                        break

                    buffer_view = buffer[:read_len]
                    dl_size += read_len
                    dl_sha1.update(buffer_view)
                    dst_fp.write(buffer_view)

                    if total_size != 0:
                        start_size += read_len

                    if progress_callback is not None:
                        progress_callback(dl_size, entry.size, start_size, total_size)

                if dl_size != entry.size:
                    # issue = "invalid_size"
                    raise DownloadCorruptedError("invalid_size")
                elif dl_sha1.hexdigest() != entry.sha1:
                    # issue = "invalid_sha1"
                    raise DownloadCorruptedError("invalid_sha1")
                else:
                    return start_size

                # else:
                #     issue = None

                # if end_callback is not None:
                #     end_callback(issue)

        # return start_size if issue is None else None

    # Version meta rules interpretation

    def interpret_rule(self, rules: list, features: Optional[dict] = None) -> bool:
        allowed = False
        for rule in rules:
            if "os" in rule:
                ros = rule["os"]
                if "name" in ros and ros["name"] != self._mc_os:
                    continue
                elif "arch" in ros and ros["arch"] != self._mc_arch:
                    continue
                elif "version" in ros and re.compile(ros["version"]).search(platform.version()) is None:
                    continue
            if "features" in rule:
                feature_valid = True
                for feat_name, feat_value in rule["features"].items():
                    if feat_name not in features or feat_value != features[feat_name]:
                        feature_valid = False
                        break
                if not feature_valid:
                    continue
            act = rule["action"]
            if act == "allow":
                allowed = True
            elif act == "disallow":
                allowed = False
        return allowed

    def interpret_args(self, args: list, features: dict) -> list:
        ret = []
        for arg in args:
            if isinstance(arg, str):
                ret.append(arg)
            else:
                if "rules" in arg:
                    if not self.interpret_rule(arg["rules"], features):
                        continue
                arg_value = arg["value"]
                if isinstance(arg_value, list):
                    ret.extend(arg_value)
                elif isinstance(arg_value, str):
                    ret.append(arg_value)
        return ret

    # Miscellenaous utilities

    @staticmethod
    def _decode_resolution(raw: str):
        return tuple(int(size) for size in raw.split("x"))

    @staticmethod
    def get_minecraft_dir() -> str:
        pf = sys.platform
        home = path.expanduser("~")
        if pf.startswith("freebsd") or pf.startswith("linux") or pf.startswith("aix") or pf.startswith("cygwin"):
            return path.join(home, ".minecraft")
        elif pf == "win32":
            return path.join(home, "AppData", "Roaming", ".minecraft")
        elif pf == "darwin":
            return path.join(home, "Library", "Application Support", "minecraft")

    @staticmethod
    def get_minecraft_os() -> str:
        pf = sys.platform
        if pf.startswith("freebsd") or pf.startswith("linux") or pf.startswith("aix") or pf.startswith("cygwin"):
            return "linux"
        elif pf == "win32":
            return "windows"
        elif pf == "darwin":
            return "osx"

    @staticmethod
    def get_minecraft_arch() -> str:
        machine = platform.machine().lower()
        return "x86" if machine == "i386" else "x86_64" if machine in ("x86_64", "amd64") else "unknown"

    @staticmethod
    def get_minecraft_archbits() -> Optional[str]:
        raw_bits = platform.architecture()[0]
        return "64" if raw_bits == "64bit" else "32" if raw_bits == "32bit" else None

    @staticmethod
    def get_classpath_separator() -> str:
        return ";" if sys.platform == "win32" else ":"

    @staticmethod
    def read_url_json(url: str) -> dict:
        return json.load(url_request.urlopen(url))

    @staticmethod
    def format_iso_date(raw: str):
        return datetime.strptime(raw.rsplit("+", 2)[0], "%Y-%m-%dT%H:%M:%S").strftime("%c")

    @classmethod
    def dict_merge(cls, dst: dict, other: dict):
        for k, v in other.items():
            if k in dst:
                if isinstance(dst[k], dict) and isinstance(other[k], dict):
                    cls.dict_merge(dst[k], other[k])
                    continue
                elif isinstance(dst[k], list) and isinstance(other[k], list):
                    dst[k].extend(other[k])
                    continue
            dst[k] = other[k]

    @staticmethod
    def format_bytes(n: float) -> str:
        if n < 1000:
            return "{:4.0f}B".format(int(n))
        elif n < 1000000:
            return "{:4.0f}kB".format(n // 1000)
        elif n < 1000000000:
            return "{:4.0f}MB".format(n // 1000000)
        else:
            return "{:4.0f}GB".format(n // 1000000000)

    @staticmethod
    def can_extract_native(filename: str) -> bool:
        return not filename.startswith("META-INF") and not filename.endswith(".git") and not filename.endswith(".sha1")


class PortableExtension:

    def __init__(self, module: Any, name: str):

        if not self.is_valid(module):
            raise ValueError("Missing 'ext_build' method.")

        self.module = module
        self.name = str(module.NAME) if hasattr(module, "NAME") else name
        self.version = str(module.VERSION) if hasattr(module, "VERSION") else "unknown"
        self.authors = module.AUTHORS if hasattr(module, "AUTHORS") else tuple()
        self.requires = module.REQUIRES if hasattr(module, "REQUIRES") else tuple()

        if not isinstance(self.authors, tuple):
            self.authors = (str(self.authors),)

        if not isinstance(self.requires, tuple):
            self.requires = (str(self.requires),)

        self.built = False
        self.instance: Optional[Any] = None

    @staticmethod
    def is_valid(module: Any) -> bool:
        return hasattr(module, "ext_build") and callable(module.ext_build)

    def build(self, pmc: PortableMC):

        from importlib import import_module

        for requirement in self.requires:
            if requirement.startswith("ext:"):
                requirement = requirement[4:]
                if pmc.get_extension(requirement) is None:
                    pmc.print("ext.missing_requirement.ext", self.name, requirement)
            else:
                try:
                    import_module(requirement)
                except ModuleNotFoundError:
                    pmc.print("ext.missing_requirement.module", self.name, requirement)
                    return False

        try:
            self.instance = self.module.ext_build()(pmc)
            self.built = True
        except (Exception,):
            pmc.print("ext.failed_to_build", self.name, traceback=True)

    def load(self):
        if self.built and hasattr(self.instance, "load") and callable(self.instance.load):
            self.instance.load()


class VersionManifest:

    def __init__(self, data: dict):
        self._data = data

    @classmethod
    def load_from_url(cls):
        return cls(PortableMC.read_url_json(VERSION_MANIFEST_URL))

    def filter_latest(self, version: str) -> Tuple[Optional[str], bool]:
        return (self._data["latest"][version], True) if version in self._data["latest"] else (version, False)

    def get_version(self, version: str) -> Optional[dict]:
        version, _alias = self.filter_latest(version)
        for version_data in self._data["versions"]:
            if version_data["id"] == version:
                return version_data
        return None

    def search_versions(self, inp: str) -> Generator[dict, None, None]:
        inp, alias = self.filter_latest(inp)
        for version_data in self._data["versions"]:
            if alias and version_data["id"] == inp:
                yield version_data
            elif not alias and inp in version_data["id"]:
                yield version_data


class AuthEntry:

    def __init__(self, client_token: str, username: str, uuid: str, access_token: str):
        self.client_token = client_token
        self.username = username
        self.uuid = uuid  # No dashes
        self.access_token = access_token

    def format_token_argument(self, legacy: bool) -> str:
        if legacy:
            return "token:{}:{}".format(self.access_token, self.uuid)
        else:
            return self.access_token

    def validate(self) -> bool:
        return self.auth_request("validate", {
            "accessToken": self.access_token,
            "clientToken": self.client_token
        }, False)[0] == 204

    def refresh(self):

        _, res = self.auth_request("refresh", {
            "accessToken": self.access_token,
            "clientToken": self.client_token
        })

        self.access_token = res["accessToken"]

    def invalidate(self):
        self.auth_request("invalidate", {
            "accessToken": self.access_token,
            "clientToken": self.client_token
        }, False)

    @classmethod
    def authenticate(cls, email_or_username: str, password: str) -> 'AuthEntry':

        _, res = cls.auth_request("authenticate", {
            "agent": {
                "name": "Minecraft",
                "version": 1
            },
            "username": email_or_username,
            "password": password,
            "clientToken": uuid4().hex
        })

        return AuthEntry(
            res["clientToken"],
            res["selectedProfile"]["name"],
            res["selectedProfile"]["id"],
            res["accessToken"]
        )

    @staticmethod
    def auth_request(req: str, payload: dict, error: bool = True) -> (int, dict):

        from http.client import HTTPResponse
        from urllib.request import Request

        req_url = AUTHSERVER_URL.format(req)
        data = json.dumps(payload).encode("ascii")
        req = Request(req_url, data, headers={
            "Content-Type": "application/json",
            "Content-Length": len(data)
        }, method="POST")

        try:
            res = url_request.urlopen(req)  # type: HTTPResponse
        except HTTPError as err:
            res = cast(HTTPResponse, err.fp)

        try:
            res_data = json.load(res)
        except JSONDecodeError:
            res_data = {}

        if error and res.status != 200:
            raise AuthError(res_data["errorMessage"])

        return res.status, res_data


class AuthDatabase:

    def __init__(self, filename: str):
        self._filename = filename
        self._entries = {}  # type: Dict[str, AuthEntry]

    def load(self):
        self._entries.clear()
        if path.isfile(self._filename):
            with open(self._filename, "rt") as fp:
                for line in fp.readlines():
                    parts = line.split(" ")
                    if len(parts) == 5:
                        self._entries[parts[0]] = AuthEntry(
                            parts[1],
                            parts[2],
                            parts[3],
                            parts[4]
                        )

    def save(self):
        with open(self._filename, "wt") as fp:
            fp.writelines(("{} {} {} {} {}".format(
                email_or_username,
                entry.client_token,
                entry.username,
                entry.uuid,
                entry.access_token
            ) for email_or_username, entry in self._entries.items()))

    def get_entry(self, email_or_username: str) -> Optional[AuthEntry]:
        return self._entries.get(email_or_username, None)

    def add_entry(self, email_or_username: str, entry: AuthEntry):
        self._entries[email_or_username] = entry

    def remove_entry(self, email_or_username: str):
        if email_or_username in self._entries:
            del self._entries[email_or_username]


class DownloadEntry:

    __slots__ = "url", "size", "sha1", "dst", "name"

    def __init__(self, url: str, size: int, sha1: str, dst: str, *, name: Optional[str] = None):
        self.url = url
        self.size = size
        self.sha1 = sha1
        self.dst = dst
        self.name = url if name is None else name

    @classmethod
    def from_version_meta_info(cls, info: dict, dst: str, *, name: Optional[str] = None) -> 'DownloadEntry':
        return DownloadEntry(info["url"], info["size"], info["sha1"], dst, name=name)


class AuthError(Exception): ...
class VersionNotFoundError(Exception): ...
class DownloadCorruptedError(Exception): ...


if __name__ == '__main__':
    PortableMC().start()


LEGACY_JVM_ARGUMENTS = [
    {
        "rules": [
            {
                "action": "allow",
                "os": {
                    "name": "osx"
                }
            }
        ],
        "value": [
            "-XstartOnFirstThread"
        ]
    },
    {
        "rules": [
            {
                "action": "allow",
                "os": {
                    "name": "windows"
                }
            }
        ],
        "value": "-XX:HeapDumpPath=MojangTricksIntelDriversForPerformance_javaw.exe_minecraft.exe.heapdump"
    },
    {
        "rules": [
            {
                "action": "allow",
                "os": {
                    "name": "windows",
                    "version": "^10\\."
                }
            }
        ],
        "value": [
            "-Dos.name=Windows 10",
            "-Dos.version=10.0"
        ]
    },
    "-Djava.library.path=${natives_directory}",
    "-Dminecraft.launcher.brand=${launcher_name}",
    "-Dminecraft.launcher.version=${launcher_version}",
    "-cp",
    "${classpath}"
]

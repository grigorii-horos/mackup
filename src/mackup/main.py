"""Mackup.

Keep your application settings in sync.
Copyright (C) 2013-2025 Laurent Raufaste <http://glop.org/>

Usage:
  mackup [options] list
  mackup [options] show <application>
  mackup [options] sync
  mackup [options] rm <path>
  mackup [options] link install
  mackup [options] link
  mackup [options] link uninstall
  mackup (-h | --help)

Options:
  -h --help                 Show this screen.
  -f --force                Force every question asked to be answered with "Yes".
  --force-no                Force every question asked to be answered with "No".
  -r --root                 Allow mackup to be run as superuser.
  -n --dry-run              Show steps without executing.
  -v --verbose              Show additional details.
  -c --config-file=<path>   Specify custom config file path.
  --version                 Show version.

Modes of action:
 - mackup list: display a list of all supported applications.
 - mackup show: display the details for a supported application.
 - mackup sync: synchronize local and remote config files in both directions.
 - mackup rm: remove a managed config file locally and from the remote folder.
 - mackup link install: moves local config files in remote folder, and links.
 - mackup link: links local config files from the remote folder.
 - mackup link uninstall: removes the links and copy config files locally.

By default, Mackup syncs all application data via
Dropbox, but may be configured to exclude applications or use a different
backend with a .mackup.cfg file.

See https://github.com/lra/mackup/tree/master/doc for more information.

"""

import sys
from typing import Any, Optional

from docopt import docopt

from . import utils
from .application import ApplicationProfile
from .appsdb import ApplicationsDatabase
from .constants import MACKUP_APP_NAME, VERSION
from .mackup import Mackup


class ColorFormatCodes:
    BLUE = "\033[34m"
    BOLD = "\033[1m"
    NORMAL = "\033[0m"


def header(text: str) -> str:
    return ColorFormatCodes.BLUE + text + ColorFormatCodes.NORMAL


def bold(text: str) -> str:
    return ColorFormatCodes.BOLD + text + ColorFormatCodes.NORMAL


def get_action_label(stats: dict[str, int]) -> Optional[str]:
    """Return a past-tense action label describing what happened."""
    if not any(stats.values()):
        return None

    backed_up = stats.get("backed_up", 0)
    restored = stats.get("restored", 0)
    synchronized = stats.get("synchronized", 0)
    deleted = stats.get("deleted", 0)
    linked = stats.get("linked", 0)
    reverted = stats.get("reverted", 0)
    errors = stats.get("errors", 0)
    if errors > 0:
        return "Failed"
    if reverted > 0:
        return "Reverted"
    if linked > 0:
        return "Linked"
    if deleted > 0:
        return "Deleted"
    if backed_up > 0 and restored > 0:
        return "Synchronized"
    if backed_up > 0:
        return "Backed up"
    if restored > 0:
        return "Restored"
    if synchronized > 0:
        return "Synchronized"
    return "Skipped"


def main() -> None:
    """Main function."""
    # Get the command line arg
    docstring = __doc__
    if not docstring:
        sys.exit(
            "Usage information is not available because __doc__ is None. "
            "This can happen when running Python with optimizations (python -OO). "
            "Please run Mackup without -OO to use the command-line interface.",
        )
    assert docstring is not None  # for type narrowing after sys.exit

    args: dict[str, Any] = docopt(docstring, version=f"Mackup {VERSION}")

    if args["--force"] and args["--force-no"]:
        sys.exit("Options --force and --force-no are mutually exclusive.")

    config_file: Optional[str] = args.get("--config-file")
    mckp: Mackup = Mackup(config_file)
    app_db: ApplicationsDatabase = ApplicationsDatabase()

    def print_app_header(app_name: str, pretty_name: str) -> None:
        if verbose:
            header_str = header("---")
            print(f"\n{header_str} {bold(f'{app_name}: {pretty_name}')} {header_str}")

    def print_app_result(stats: dict[str, int], app_name: str, pretty_name: str) -> None:
        action = get_action_label(stats)
        if action is None:
            return
        print(utils.colorize_message(f"{action} {pretty_name}"))

    # If we want to answer mackup with "yes" for each question
    if args["--force"]:
        utils.FORCE_YES = True

    # If we want to answer mackup with "no" for each question
    if args["--force-no"]:
        utils.FORCE_NO = True

    # Allow mackup to be run as root
    if args["--root"]:
        utils.CAN_RUN_AS_ROOT = True

    dry_run: bool = args["--dry-run"]

    verbose: bool = args["--verbose"]

    # mackup list
    if args["list"]:
        # Display the list of supported applications
        mckp.check_for_usable_environment()
        output: str = "Supported applications:\n"
        for app_name in sorted(app_db.get_app_names()):
            output += f" - {app_name}\n"
        output += "\n"
        output += (
            f"{len(app_db.get_app_names())} applications supported in "
            f"Mackup v{VERSION}"
        )
        print(output)

    # mackup show <application>
    elif args["show"]:
        mckp.check_for_usable_environment()
        requested_app_name: str = args["<application>"]

        # Make sure the app exists
        if requested_app_name not in app_db.get_app_names():
            sys.exit(f"Unsupported application: {requested_app_name}")
        print(f"Name: {app_db.get_name(requested_app_name)}")
        print("Configuration files:")
        for file in app_db.get_files(requested_app_name):
            print(f" - {file}")

    # mackup sync
    elif args["sync"]:
        mckp.check_for_usable_backup_env()

        # Synchronize in two phases:
        # one pass per file: decide direction by mtime and do one action.
        for app_name in sorted(mckp.get_apps_to_backup()):
            pretty_name = app_db.get_name(app_name)
            app = ApplicationProfile(mckp, app_db.get_file_mappings(app_name), dry_run, verbose)
            print_app_header(app_name, pretty_name)
            stats = app.sync_files()
            print_app_result(stats, app_name, pretty_name)

    # mackup rm <path>
    elif args["rm"]:
        mckp.check_for_usable_backup_env()

        requested_path = ApplicationProfile.normalize_relative_path(args["<path>"])
        if (
            requested_path == ".."
            or requested_path.startswith("../")
            or requested_path.startswith("..\\")
            or requested_path.startswith("/")
        ):
            sys.exit(f"Refusing to remove unmanaged path: {args['<path>']}")

        matching_app_name: Optional[str] = None
        matching_mapping: Optional[tuple[str, str]] = None
        for app_name in sorted(mckp.get_apps_to_backup()):
            for local_filename, backup_filename in sorted(
                app_db.get_file_mappings(app_name),
            ):
                if (
                    ApplicationProfile.normalize_relative_path(local_filename)
                    == requested_path
                ):
                    matching_app_name = app_name
                    matching_mapping = (local_filename, backup_filename)
                    break
            if matching_mapping is not None:
                break

        if matching_app_name is None or matching_mapping is None:
            sys.exit(f"Unsupported or unmanaged path: {args['<path>']}")

        pretty_name = app_db.get_name(matching_app_name)
        app = ApplicationProfile(mckp, {matching_mapping}, dry_run, verbose)
        print_app_header(matching_app_name, pretty_name)
        stats = app.remove_file(*matching_mapping)
        print_app_result(stats, matching_app_name, pretty_name)

    # mackup link install
    elif args["link"] and args["install"]:
        # Check the env where the command is being run
        mckp.check_for_usable_backup_env()

        # Create a link for each application
        for app_name in sorted(mckp.get_apps_to_backup()):
            pretty_name = app_db.get_name(app_name)
            app = ApplicationProfile(mckp, app_db.get_file_mappings(app_name), dry_run, verbose)
            print_app_header(app_name, pretty_name)
            stats = app.link_install()
            print_app_result(stats, app_name, pretty_name)

    # mackup link uninstall
    elif args["link"] and args["uninstall"]:
        # Check the env where the command is being run
        mckp.check_for_usable_restore_env()

        if dry_run or (
            utils.confirm(
                "You are going to uninstall Mackup.\n"
                "Every configuration file, setting and dotfile"
                " managed by Mackup will be unlinked and copied back"
                " to their original place, in your home folder.\n"
                "Are you sure?",
            )
        ):
            # Uninstall the apps except Mackup, which we'll uninstall last, to
            # keep the settings as long as possible
            app_names = mckp.get_apps_to_backup()
            app_names.discard(MACKUP_APP_NAME)

            for app_name in sorted(app_names):
                pretty_name = app_db.get_name(app_name)
                app = ApplicationProfile(
                    mckp, app_db.get_file_mappings(app_name), dry_run, verbose,
                )
                print_app_header(app_name, pretty_name)
                stats = app.link_uninstall()
                print_app_result(stats, app_name, pretty_name)
 

            # Restore the Mackup config before any other config, as we might
            # need it to know about custom settings
            mackup_app = ApplicationProfile(
                mckp, app_db.get_file_mappings(MACKUP_APP_NAME), dry_run, verbose,
            )
            pretty_name = app_db.get_name(MACKUP_APP_NAME)
            print_app_header(MACKUP_APP_NAME, pretty_name)
            stats = mackup_app.link_uninstall()
            print_app_result(stats, MACKUP_APP_NAME, pretty_name)

            # Delete the Mackup folder in Dropbox
            # Don't delete this as there might be other Macs that aren't
            # uninstalled yet
            # delete(mckp.mackup_folder)

            print(
                "\n"
                "All your files have been put back into place. You can now"
                " safely uninstall Mackup.\n"
                "\n"
                "Thanks for using Mackup!",
            )

    # mackup link
    elif args["link"]:
        # Check the env where the command is being run
        mckp.check_for_usable_restore_env()

        # Restore the Mackup config before any other config, as we might need
        # it to know about custom settings
        mackup_app = ApplicationProfile(
            mckp, app_db.get_file_mappings(MACKUP_APP_NAME), dry_run, verbose,
        )
        mackup_pretty = app_db.get_name(MACKUP_APP_NAME)
        print_app_header(MACKUP_APP_NAME, mackup_pretty)
        stats = mackup_app.link()
        print_app_result(stats, MACKUP_APP_NAME, mackup_pretty)

        # Initialize again the apps db, as the Mackup config might have changed
        # it
        mckp = Mackup(config_file)
        app_db = ApplicationsDatabase()

        # Restore the rest of the app configs, using the restored Mackup config
        app_names = mckp.get_apps_to_backup()
        # Mackup has already been done
        app_names.discard(MACKUP_APP_NAME)

        for app_name in sorted(app_names):
            pretty_name = app_db.get_name(app_name)
            app = ApplicationProfile(mckp, app_db.get_file_mappings(app_name), dry_run, verbose)
            print_app_header(app_name, pretty_name)
            stats = app.link()
            print_app_result(stats, app_name, pretty_name)

    # Delete the tmp folder
    mckp.clean_temp_folder()

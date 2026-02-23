"""
Application Profile.

An Application Profile contains all the information about an application in
Mackup. Name, files, ...
"""

import os

from . import utils
from .mackup import Mackup


class ApplicationProfile:
    """Instantiate this class with application specific data."""

    def __init__(
        self, mackup: Mackup, files: set[str], dry_run: bool, verbose: bool,
    ) -> None:
        """
        Create an ApplicationProfile instance.

        Args:
            mackup (Mackup)
            files (list)
        """
        assert isinstance(mackup, Mackup)
        assert isinstance(files, set)

        self.mackup: Mackup = mackup
        self.files: list[str] = sorted(files)
        self.dry_run: bool = dry_run
        self.verbose: bool = verbose

    @staticmethod
    def _print(message: str) -> None:
        """Print a user-facing message with terminal color highlighting."""
        print(utils.colorize_message(message))

    def get_filepaths(self, filename: str) -> tuple[str, str]:
        """
        Get home and mackup filepaths for given file

        Args:
            filename (str)

        Returns:
            home_filepath, mackup_filepath (str, str)
        """
        return (
            os.path.join(os.environ["HOME"], filename),
            os.path.join(self.mackup.mackup_folder, filename),
        )

    @staticmethod
    def get_effective_mtime(path: str) -> float:
        """
        Return comparable mtime for a file or directory.

        For directories, the newest mtime in the whole tree is used so changes
        to nested files/folders are considered during backup/restore/sync.
        """
        latest_mtime = os.path.getmtime(path)

        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for name in dirs + files:
                    entry_mtime = os.path.getmtime(os.path.join(root, name))
                    if entry_mtime > latest_mtime:
                        latest_mtime = entry_mtime

        return latest_mtime

    @staticmethod
    def collect_relative_entries(root: str) -> set[str]:
        """Collect all file and directory entries under root (relative paths)."""
        entries: set[str] = set()
        for cur_root, dirs, files in os.walk(root):
            for name in dirs + files:
                entries.add(os.path.relpath(os.path.join(cur_root, name), root))
        return entries

    def copy_item(self, source: str, destination: str) -> None:
        """
        Copy source item to destination, replacing destination when types differ.
        """
        if os.path.lexists(destination):
            source_is_dir = os.path.isdir(source)
            destination_is_dir = os.path.isdir(destination)
            if source_is_dir != destination_is_dir:
                utils.delete(destination)
        utils.copy(source, destination)

    @staticmethod
    def ensure_directory(path: str, mode_from: str) -> None:
        """Ensure directory exists and mirror mtime from mode_from."""
        os.makedirs(path, exist_ok=True)
        dir_mtime = os.path.getmtime(mode_from)
        os.utime(path, (dir_mtime, dir_mtime))

    def sync_directory_entries_one_way(
        self, source_dir: str, destination_dir: str, source_wins: bool, dry_run: bool,
    ) -> bool:
        """
        Sync directory entries from source to destination by per-entry mtime.

        When source_wins is True, newer source entries overwrite destination.
        When source_wins is False, this still compares mtimes but never copies
        destination back to source; useful for skip-only behavior.
        """
        changed = False
        source_root_mtime = os.path.getmtime(source_dir)
        destination_root_mtime = os.path.getmtime(destination_dir)
        if source_wins and source_root_mtime > destination_root_mtime:
            if not dry_run:
                os.utime(destination_dir, (source_root_mtime, source_root_mtime))
            changed = True

        source_entries = self.collect_relative_entries(source_dir)
        destination_entries = self.collect_relative_entries(destination_dir)
        all_entries = sorted(source_entries | destination_entries)

        for entry in all_entries:
            source_entry = os.path.join(source_dir, entry)
            destination_entry = os.path.join(destination_dir, entry)
            source_exists = os.path.exists(source_entry)
            destination_exists = os.path.exists(destination_entry)

            if source_exists and destination_exists:
                source_is_dir = os.path.isdir(source_entry)
                destination_is_dir = os.path.isdir(destination_entry)

                if source_is_dir and destination_is_dir:
                    source_mtime = os.path.getmtime(source_entry)
                    destination_mtime = os.path.getmtime(destination_entry)
                    if source_wins and source_mtime > destination_mtime:
                        if not dry_run:
                            os.utime(destination_entry, (source_mtime, source_mtime))
                        changed = True
                    continue

                source_mtime = self.get_effective_mtime(source_entry)
                destination_mtime = self.get_effective_mtime(destination_entry)

                if source_wins and source_mtime > destination_mtime:
                    if not dry_run:
                        if source_is_dir:
                            if os.path.lexists(destination_entry) and not destination_is_dir:
                                utils.delete(destination_entry)
                            self.ensure_directory(destination_entry, source_entry)
                        else:
                            self.copy_item(source_entry, destination_entry)
                    changed = True
            elif source_exists:
                if not dry_run:
                    if os.path.isdir(source_entry):
                        self.ensure_directory(destination_entry, source_entry)
                    else:
                        self.copy_item(source_entry, destination_entry)
                changed = True

        return changed

    def sync_directory_entries(self, home_dir: str, backup_dir: str) -> bool:
        """
        Synchronize two directories by comparing mtime per entry.

        Returns True if any files were actually copied or updated.
        """
        changed = False

        home_root_mtime = os.path.getmtime(home_dir)
        backup_root_mtime = os.path.getmtime(backup_dir)
        if home_root_mtime > backup_root_mtime:
            os.utime(backup_dir, (home_root_mtime, home_root_mtime))
        elif backup_root_mtime > home_root_mtime:
            os.utime(home_dir, (backup_root_mtime, backup_root_mtime))

        home_entries = self.collect_relative_entries(home_dir)
        backup_entries = self.collect_relative_entries(backup_dir)
        all_entries = sorted(home_entries | backup_entries)

        for entry in all_entries:
            home_entry = os.path.join(home_dir, entry)
            backup_entry = os.path.join(backup_dir, entry)
            home_exists = os.path.exists(home_entry)
            backup_exists = os.path.exists(backup_entry)

            if home_exists and backup_exists:
                home_is_dir = os.path.isdir(home_entry)
                backup_is_dir = os.path.isdir(backup_entry)

                if home_is_dir and backup_is_dir:
                    home_mtime = os.path.getmtime(home_entry)
                    backup_mtime = os.path.getmtime(backup_entry)
                    if home_mtime > backup_mtime:
                        os.utime(backup_entry, (home_mtime, home_mtime))
                    elif backup_mtime > home_mtime:
                        os.utime(home_entry, (backup_mtime, backup_mtime))
                    continue

                if (not home_is_dir) and (not backup_is_dir):
                    home_mtime = os.path.getmtime(home_entry)
                    backup_mtime = os.path.getmtime(backup_entry)
                    if home_mtime > backup_mtime:
                        if self.verbose:
                            self._print(f"Backing up {entry}")
                        self.copy_item(home_entry, backup_entry)
                        changed = True
                    elif backup_mtime > home_mtime:
                        if self.verbose:
                            self._print(f"Restoring {entry}")
                        self.copy_item(backup_entry, home_entry)
                        changed = True
                    continue

                home_mtime = self.get_effective_mtime(home_entry)
                backup_mtime = self.get_effective_mtime(backup_entry)
                if home_mtime >= backup_mtime:
                    if home_is_dir:
                        if os.path.lexists(backup_entry) and not backup_is_dir:
                            utils.delete(backup_entry)
                        self.ensure_directory(backup_entry, home_entry)
                    else:
                        if self.verbose:
                            self._print(f"Backing up {entry}")
                        self.copy_item(home_entry, backup_entry)
                    changed = True
                else:
                    if backup_is_dir:
                        if os.path.lexists(home_entry) and not home_is_dir:
                            utils.delete(home_entry)
                        self.ensure_directory(home_entry, backup_entry)
                    else:
                        if self.verbose:
                            self._print(f"Restoring {entry}")
                        self.copy_item(backup_entry, home_entry)
                    changed = True
            elif home_exists:
                if self.verbose:
                    self._print(f"Backing up {entry}")
                if os.path.isdir(home_entry):
                    self.ensure_directory(backup_entry, home_entry)
                else:
                    self.copy_item(home_entry, backup_entry)
                changed = True
            elif backup_exists:
                if self.verbose:
                    self._print(f"Restoring {entry}")
                if os.path.isdir(backup_entry):
                    self.ensure_directory(home_entry, backup_entry)
                else:
                    self.copy_item(backup_entry, home_entry)
                changed = True

        return changed

    def copy_files_to_mackup_folder(self) -> dict[str, int]:
        """
        Backup the application config files to the Mackup folder.

        Algorithm:
            for config_file
                if config_file exists and is a real file/folder
                    if home/file is a symlink pointing to mackup/file
                        skip (already backed up via link install)
                    if exists mackup/file
                        are you sure?
                        if sure
                            rm mackup/file
                    cp home/file mackup/file
        """
        stats: dict[str, int] = {"backed_up": 0, "skipped": 0, "errors": 0}

        for filename in self.files:
            (home_filepath, mackup_filepath) = self.get_filepaths(filename)

            # If config_file exists and is a real file/folder
            if (os.path.isfile(home_filepath) or os.path.isdir(home_filepath)):
                # Check if home file is a symlink pointing to mackup file
                # (already backed up via link install)
                if (
                    os.path.islink(home_filepath)
                    and os.path.exists(mackup_filepath)
                    and os.path.samefile(home_filepath, mackup_filepath)
                ):
                    if self.verbose:
                        self._print(
                            f"Skipping {home_filepath}\n"
                            f"  already linked to\n  {mackup_filepath}",
                        )
                    stats["skipped"] += 1
                    continue

                # If exists mackup/file
                if os.path.lexists(mackup_filepath):
                    if os.path.exists(mackup_filepath):
                        if os.path.isdir(home_filepath) and os.path.isdir(mackup_filepath):
                            changed = self.sync_directory_entries_one_way(
                                home_filepath, mackup_filepath, source_wins=True,
                                dry_run=self.dry_run,
                            )
                            if not changed:
                                if self.verbose:
                                    self._print(
                                        f"Skipping {home_filepath}\n"
                                        f"  backup is newer or same age at\n  {mackup_filepath}",
                                    )
                                stats["skipped"] += 1
                            else:
                                if self.verbose:
                                    self._print(
                                        f"Backing up\n  {home_filepath}\n  to\n  {mackup_filepath} ...",
                                    )
                                stats["backed_up"] += 1
                            continue

                        source_mtime = self.get_effective_mtime(home_filepath)
                        backup_mtime = self.get_effective_mtime(mackup_filepath)
                        if source_mtime <= backup_mtime:
                            if self.verbose:
                                self._print(
                                    f"Skipping {home_filepath}\n"
                                    f"  backup is newer or same age at\n  {mackup_filepath}",
                                )
                            stats["skipped"] += 1
                            continue

                if self.verbose:
                    self._print(
                        f"Backing up\n  {home_filepath}\n  to\n  {mackup_filepath} ...",
                    )

                if self.dry_run:
                    stats["backed_up"] += 1
                    continue

                if os.path.lexists(mackup_filepath):
                    # Local file is newer (or backup is broken link), overwrite silently.
                    utils.delete(mackup_filepath)

                # Copy the file
                try:
                    utils.copy(home_filepath, mackup_filepath)
                    stats["backed_up"] += 1
                except PermissionError as e:
                    self._print(
                        f"Error: Unable to copy file from {home_filepath} to "
                        f"{mackup_filepath} due to permission issue: {e}",
                    )
                    stats["errors"] += 1

        return stats

    def copy_files_from_mackup_folder(self) -> dict[str, int]:
        """
        Recover the application config files from the Mackup folder.

        Algorithm:
            for config_file
                if config_file exists in mackup and is a real file/folder
                    if exists home/file and mtime(home) >= mtime(mackup)
                        skip
                    if exists home/file and --force
                        rm home/file
                    cp mackup/file home/file
        """
        stats: dict[str, int] = {"restored": 0, "skipped": 0, "errors": 0}

        for filename in self.files:
            (home_filepath, mackup_filepath) = self.get_filepaths(filename)

            # If config_file exists in mackup and is a real file/folder
            if (os.path.isfile(mackup_filepath) or os.path.isdir(mackup_filepath)):
                # If local file is newer (or same age), keep local version by default.
                if (
                    os.path.exists(home_filepath)
                    and not utils.FORCE_YES
                    and os.path.isdir(home_filepath)
                    and os.path.isdir(mackup_filepath)
                ):
                    changed = self.sync_directory_entries_one_way(
                        mackup_filepath, home_filepath, source_wins=True,
                        dry_run=self.dry_run,
                    )
                    if not changed:
                        if self.verbose:
                            self._print(
                                f"Skipping {home_filepath}\n"
                                f"  local file is newer or same age than\n  {mackup_filepath}",
                            )
                        stats["skipped"] += 1
                    else:
                        if self.verbose:
                            self._print(
                                f"Restoring\n  {mackup_filepath}\n  to\n  {home_filepath} ...",
                            )
                        stats["restored"] += 1
                    continue

                if (
                    os.path.exists(home_filepath)
                    and not utils.FORCE_YES
                    and self.get_effective_mtime(home_filepath)
                    >= self.get_effective_mtime(mackup_filepath)
                ):
                    if self.verbose:
                        self._print(
                            f"Skipping {home_filepath}\n"
                            f"  local file is newer or same age than\n  {mackup_filepath}",
                        )
                    stats["skipped"] += 1
                    continue

                if self.verbose:
                    self._print(
                        f"Restoring\n  {mackup_filepath}\n  to\n  {home_filepath} ...",
                    )

                if self.dry_run:
                    stats["restored"] += 1
                    continue

                # If exists home/file, overwrite it.
                if os.path.lexists(home_filepath):
                    utils.delete(home_filepath)

                # Copy the file
                try:
                    utils.copy(mackup_filepath, home_filepath)
                    stats["restored"] += 1
                except PermissionError as e:
                    self._print(
                        f"Error: Unable to copy file from {mackup_filepath} to "
                        f"{home_filepath} due to permission issue: {e}",
                    )
                    stats["errors"] += 1

        return stats

    def sync_files(self) -> dict[str, int]:
        """Synchronize files between home and Mackup using mtime."""
        stats: dict[str, int] = {
            "backed_up": 0, "restored": 0, "synchronized": 0,
            "skipped": 0, "errors": 0,
        }

        for filename in self.files:
            (home_filepath, mackup_filepath) = self.get_filepaths(filename)

            home_exists = os.path.isfile(home_filepath) or os.path.isdir(home_filepath)
            backup_exists = os.path.isfile(mackup_filepath) or os.path.isdir(
                mackup_filepath
            )

            action: str | None = None
            if home_exists and backup_exists:
                # Already linked/same inode, nothing to do.
                if os.path.samefile(home_filepath, mackup_filepath):
                    if self.verbose:
                        self._print(
                            f"Skipping {home_filepath}\n"
                            f"  already linked to\n  {mackup_filepath}",
                        )
                    stats["skipped"] += 1
                    continue

                # For directories we merge by entry mtime, not whole-tree mtime.
                if os.path.isdir(home_filepath) and os.path.isdir(mackup_filepath):
                    if self.dry_run:
                        home_to_backup_changes = self.sync_directory_entries_one_way(
                            home_filepath, mackup_filepath, source_wins=True, dry_run=True,
                        )
                        backup_to_home_changes = self.sync_directory_entries_one_way(
                            mackup_filepath, home_filepath, source_wins=True, dry_run=True,
                        )
                        dir_changed = home_to_backup_changes or backup_to_home_changes
                        if self.verbose:
                            if dir_changed:
                                self._print(
                                    f"Synchronizing\n  {home_filepath}\n  with\n  {mackup_filepath} ...",
                                )
                            else:
                                self._print(
                                    f"Skipping {home_filepath}\n"
                                    f"  already in sync with\n  {mackup_filepath}",
                                )
                        if dir_changed:
                            stats["synchronized"] += 1
                        else:
                            stats["skipped"] += 1
                        continue

                    try:
                        dir_changed = self.sync_directory_entries(home_filepath, mackup_filepath)
                        if dir_changed:
                            if self.verbose:
                                self._print(
                                    f"Synchronizing\n  {home_filepath}\n  with\n  {mackup_filepath} ...",
                                )
                            stats["synchronized"] += 1
                        else:
                            if self.verbose:
                                self._print(
                                    f"Skipping {home_filepath}\n"
                                    f"  already in sync with\n  {mackup_filepath}",
                                )
                            stats["skipped"] += 1
                    except PermissionError as e:
                        self._print(
                            "Error: Unable to sync directory entries between "
                            f"{home_filepath} and {mackup_filepath} due to permission issue: {e}",
                        )
                        stats["errors"] += 1
                    continue

                home_mtime = self.get_effective_mtime(home_filepath)
                backup_mtime = self.get_effective_mtime(mackup_filepath)
                if home_mtime > backup_mtime:
                    action = "backup"
                elif backup_mtime > home_mtime:
                    action = "restore"
            elif home_exists:
                action = "backup"
            elif backup_exists:
                action = "restore"
            else:
                # Missing on both sides: no-op, do not count as a user-visible skip.
                continue

            if action is None:
                if self.verbose:
                    self._print(
                        f"Skipping {home_filepath}\n"
                        f"  same mtime as\n  {mackup_filepath}",
                    )
                stats["skipped"] += 1
                continue

            if action == "backup":
                if self.verbose:
                    self._print(
                        f"Backing up\n  {home_filepath}\n  to\n  {mackup_filepath} ...",
                    )

                if self.dry_run:
                    stats["backed_up"] += 1
                    continue

                if os.path.lexists(mackup_filepath):
                    utils.delete(mackup_filepath)

                try:
                    utils.copy(home_filepath, mackup_filepath)
                    stats["backed_up"] += 1
                except PermissionError as e:
                    self._print(
                        f"Error: Unable to copy file from {home_filepath} to "
                        f"{mackup_filepath} due to permission issue: {e}",
                    )
                    stats["errors"] += 1
            else:
                if self.verbose:
                    self._print(
                        f"Restoring\n  {mackup_filepath}\n  to\n  {home_filepath} ...",
                    )

                if self.dry_run:
                    stats["restored"] += 1
                    continue

                if os.path.lexists(home_filepath):
                    utils.delete(home_filepath)

                try:
                    utils.copy(mackup_filepath, home_filepath)
                    stats["restored"] += 1
                except PermissionError as e:
                    self._print(
                        f"Error: Unable to copy file from {mackup_filepath} to "
                        f"{home_filepath} due to permission issue: {e}",
                    )
                    stats["errors"] += 1

        return stats

    def link_install(self) -> dict[str, int]:
        """
        Create the application config file links.

        Algorithm:
            if exists home/file
              if home/file is a real file
                if exists mackup/file
                  are you sure?
                  if sure
                    rm mackup/file
                    mv home/file mackup/file
                    link mackup/file home/file
                else
                  mv home/file mackup/file
                  link mackup/file home/file
        """
        stats: dict[str, int] = {"linked": 0, "skipped": 0}

        # For each file used by the application
        for filename in self.files:
            (home_filepath, mackup_filepath) = self.get_filepaths(filename)

            # If the file exists and is not already a link pointing to Mackup
            if (os.path.isfile(home_filepath) or os.path.isdir(home_filepath)) and not (
                os.path.islink(home_filepath)
                and (os.path.isfile(mackup_filepath) or os.path.isdir(mackup_filepath))
                and os.path.samefile(home_filepath, mackup_filepath)
            ):
                if self.verbose:
                    self._print(
                        f"Backing up\n  {home_filepath}\n  to\n  {mackup_filepath} ...",
                    )

                if self.dry_run:
                    stats["linked"] += 1
                    continue

                # Check if we already have a backup
                if os.path.exists(mackup_filepath):
                    # Name it right
                    if os.path.isfile(mackup_filepath):
                        file_type = "file"
                    elif os.path.isdir(mackup_filepath):
                        file_type = "folder"
                    elif os.path.islink(mackup_filepath):
                        file_type = "link"
                    else:
                        raise ValueError(f"Unsupported file: {mackup_filepath}")

                    # Ask the user if he really wants to replace it
                    if utils.confirm(
                        f"A {file_type} named {mackup_filepath} already exists in the"
                        " backup.\nAre you sure that you want to"
                        " replace it?",
                    ):
                        # Delete the file in Mackup
                        utils.delete(mackup_filepath)
                        # Copy the file
                        utils.copy(home_filepath, mackup_filepath)
                        # Delete the file in the home
                        utils.delete(home_filepath)
                        # Link the backuped file to its original place
                        utils.link(mackup_filepath, home_filepath)
                        stats["linked"] += 1
                    else:
                        stats["skipped"] += 1
                else:
                    # Copy the file
                    utils.copy(home_filepath, mackup_filepath)
                    # Delete the file in the home
                    utils.delete(home_filepath)
                    # Link the backuped file to its original place
                    utils.link(mackup_filepath, home_filepath)
                    stats["linked"] += 1
            elif self.verbose:
                if os.path.exists(home_filepath):
                    self._print(
                        f"Doing nothing\n  {home_filepath}\n  "
                        f"is already backed up to\n  {mackup_filepath}",
                    )
                elif os.path.islink(home_filepath):
                    self._print(
                        f"Doing nothing\n  {home_filepath}\n  "
                        "is a broken link, you might want to fix it.",
                    )
                else:
                    self._print(f"Doing nothing\n  {home_filepath}\n  does not exist")

        return stats

    def link(self) -> dict[str, int]:
        """
        Link the application config files.

        Algorithm:
            if exists mackup/file
              if exists home/file
                are you sure?
                if sure
                  rm home/file
                  link mackup/file home/file
              else
                link mackup/file home/file
        """
        stats: dict[str, int] = {"linked": 0, "skipped": 0}

        # For each file used by the application
        for filename in self.files:
            (home_filepath, mackup_filepath) = self.get_filepaths(filename)

            # If the file exists and is not already pointing to the mackup file
            # and the folder makes sense on the current platform (Don't sync
            # any subfolder of ~/Library on GNU/Linux)
            file_or_dir_exists: bool = os.path.isfile(mackup_filepath) or os.path.isdir(
                mackup_filepath,
            )
            pointing_to_mackup: bool = (
                os.path.islink(home_filepath)
                and os.path.exists(mackup_filepath)
                and os.path.samefile(mackup_filepath, home_filepath)
            )
            supported: bool = utils.can_file_be_synced_on_current_platform(filename)

            if file_or_dir_exists and not pointing_to_mackup and supported:
                if self.verbose:
                    self._print(
                        f"Restoring\n  linking {home_filepath}\n"
                        f"  to      {mackup_filepath} ...",
                    )

                if self.dry_run:
                    stats["linked"] += 1
                    continue

                # Check if there is already a file in the home folder
                if os.path.exists(home_filepath):
                    # Name it right
                    if os.path.isfile(home_filepath):
                        file_type = "file"
                    elif os.path.isdir(home_filepath):
                        file_type = "folder"
                    elif os.path.islink(home_filepath):
                        file_type = "link"
                    else:
                        raise ValueError(f"Unsupported file: {home_filepath}")

                    if utils.confirm(
                        f"You already have a {file_type} at {home_filepath}.\n"
                        "Do you want to replace it with your backup?",
                    ):
                        utils.delete(home_filepath)
                        utils.link(mackup_filepath, home_filepath)
                        stats["linked"] += 1
                    else:
                        stats["skipped"] += 1
                else:
                    utils.link(mackup_filepath, home_filepath)
                    stats["linked"] += 1
            elif self.verbose:
                if os.path.exists(home_filepath):
                    self._print(
                        f"Doing nothing\n  {mackup_filepath}\n"
                        f"  already linked by\n  {home_filepath}",
                    )
                elif os.path.islink(home_filepath):
                    self._print(
                        f"Doing nothing\n  {home_filepath}\n  "
                        "is a broken link, you might want to fix it.",
                    )
                else:
                    self._print(
                        f"Doing nothing\n  {mackup_filepath}\n  does not exist",
                    )

        return stats

    def link_uninstall(self) -> dict[str, int]:
        """
        Removes links and copy config files from the remote folder locally.

        Algorithm:
            for each file in config
                if mackup/file exists
                    if home/file exists
                        delete home/file
                    copy mackup/file home/file
        """
        stats: dict[str, int] = {"reverted": 0, "skipped": 0, "warnings": 0}

        # For each file used by the application
        for filename in self.files:
            (home_filepath, mackup_filepath) = self.get_filepaths(filename)

            # If the mackup file exists
            if os.path.isfile(mackup_filepath) or os.path.isdir(mackup_filepath):
                # Check if there is a corresponding file in the home folder
                if os.path.exists(home_filepath):
                    # If the home file is not a link or does not point to the
                    # mackup file, display a warning and skip it.
                    if not os.path.islink(home_filepath) or not os.path.samefile(
                        home_filepath, mackup_filepath,
                    ):
                        self._print(
                            f'Warning: the file in your home "{home_filepath}" '
                            f"does not point to the original file in Mackup "
                            f"{mackup_filepath}, skipping...",
                        )
                        stats["warnings"] += 1
                        continue
                    if self.verbose:
                        self._print(
                            f"Reverting {mackup_filepath}\n at {home_filepath} ...",
                        )

                    if self.dry_run:
                        stats["reverted"] += 1
                        continue

                    # If there is, delete it as we are gonna copy the Dropbox
                    # one there
                    utils.delete(home_filepath)

                    # Copy the Dropbox file to the home folder
                    utils.copy(mackup_filepath, home_filepath)
                    stats["reverted"] += 1
            elif self.verbose:
                self._print(f"Doing nothing, {mackup_filepath} does not exist")

        return stats

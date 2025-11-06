# ZFS Snapshot Manager

A Python script to automatically create and prune ZFS snapshots based on a "grandfather-father-son" retention policy. All configuration is handled via an external JSON config file.

## Features

* **Automated Snapshots:** Creates timestamped snapshots for a list of specified ZFS datasets.
* **Automated Pruning:** Deletes old snapshots based on a configurable retention policy (daily, weekly, monthly).
* **External Configuration:** All settings are managed in a `zfs_config.json` file, not in the script.
* **Safe by Default:** Includes a `dry_run` mode (enabled by default) to test logic without deleting anything.
* **Logging:** All actions are logged to `zfs_manager.log` for easy auditing.
* **Flexible:** A command-line argument (`-c` or `--config`) can be used to point to a custom config file.

---

## Requirements

* Python 3.x
* `zfsutils-linux` (or the equivalent package that provides the `zfs` command).
* `sudo` privileges (the script must be run as root or with `sudo` to execute `zfs` commands).

---

## Setup & Configuration

1.  Make the script executable:
    ```bash
    chmod +x /home/<path>/zfs_manager.py
    ```

3.  In the same directory, create a `zfs_config.json` file with the following structure:

    **`zfs_config.json`**
    ```json
    {
      "dry_run": true,
      "snapshot_prefix": "autosnap",
      "datasets": [
        "shared/immich-library",
        "shared/trilium",
        "shared/homepage-config",
        "shared/torrent-config"
      ],
      "retention": {
        "daily": 7,
        "weekly": 4,
        "monthly": 3
      }
    }
    ```

### Configuration Options

* `dry_run` (bool): If `true`, the script will log all actions but will **not** destroy any snapshots. **Set this to `false` to go live.**
* `snapshot_prefix` (str): The prefix used to name snapshots. This is how the script identifies which snapshots it "owns" and is allowed to prune.
* `datasets` (list): A list of ZFS dataset names to snapshot.
* `retention` (dict): The "grandfather-father-son" policy.
    * `daily`: Keep the most recent N daily snapshots.
    * `weekly`: Keep the first snapshot of the week for N weeks.
    * `monthly`: Keep the first snapshot of the month for N months.

---

## Usage

### Manual Execution

You can run the script manually at any time. Because it uses `sudo` internally to call `zfs`, you must run the script itself with `sudo`.

```bash
# Run with the default config (zfs_config.json in the same directory)
sudo /home/ian/scripts/zfs_manager.py

# Run with a custom config file
sudo /home/ian/scripts/zfs_manager.py -c /path/to/my-config.json
```
While dry_run is true, this is completely safe to test your logic.

---

## Automation with `cron`

The best way to use this script is to run it automatically every night.

1.  Open the **root** user's crontab (this is required so the script has permission to run `sudo zfs`):
    ```bash
    sudo crontab -e
    ```
    (Select `vim` or your preferred editor if prompted).

2.  Add the following line to the bottom of the file. This will run the script every day at 1:00 AM.

    ```cron
    0 1 * * * /usr/bin/python3 /home/<path>/zfs_manager.py
    ```
    * `0 1 * * *`: The schedule (1:00 AM daily).
    * `/usr/bin/python3`: The absolute path to your Python 3 interpreter.
    * `/home/<path>/zfs_manager.py`: The absolute path to your script.

3.  Save and quit the editor.

4.  **Final Step:** Don't forget to edit your `zfs_config.json` and set `"dry_run": false`.

---

## Logging

All script operations, errors, and `dry_run` actions are logged to `zfs_manager.log` in the same directory as the script.


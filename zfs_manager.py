#!/usr/bin/env python3

import subprocess
import logging
import json
import argparse
import os
from datetime import datetime, timedelta
from typing import List, Dict, Set, Optional, Tuple, Any

# This will be populated by the load_config function
CONFIG = {}

# write logging file to this directory
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("zfs_manager.log"),
        logging.StreamHandler()
    ]
)

#------------------------------------------------------
#
#------------------------------------------------------
def load_config(config_path: str) -> None:
    """Loads configuration from the specified JSON file."""
    global CONFIG
    try:
        with open(config_path, 'r') as f:
            CONFIG = json.load(f)
        logging.info(f"Successfully loaded config from {config_path}")
    except FileNotFoundError:
        logging.critical(f"Config file not found at {config_path}. Exiting.")
        exit(1)
    except json.JSONDecodeError:
        logging.critical(f"Failed to decode JSON from {config_path}. Check for syntax errors. Exiting.")
        exit(1)
    except Exception as e:
        logging.critical(f"An error occurred loading config: {e}. Exiting.")
        exit(1)

#------------------------------------------------------
#
#------------------------------------------------------
def run_zfs_command(cmd_list: List[str]) -> Tuple[bool, str]:
    """ Runs a ZFS command, logs it, returns (success_bool, output_str) """
    try:
        full_cmd = ["sudo", "zfs"] + cmd_list
        logging.info(f"Running: {' '.join(full_cmd)}")

        # in dry run, don't destroy anything
        if CONFIG.get("dry_run", True) and cmd_list[0] == "destroy":
            logging.info("  -> DRY_RUN: Skipped destroy")
            return True, ""

        result = subprocess.run(full_cmd, capture_output=True, text=True, check=True)
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {' '.join(full_cmd)}")
        logging.error(f"STDOUT: {e.stdout}")
        logging.error(f"STDERR: {e.stderr}")

#------------------------------------------------------
#
#------------------------------------------------------
def parse_snapshot_name(snap_name_full: str) -> Tuple[Optional[str], Optional[str], Optional[datetime]]:
    """
    Parses a snapshot name like 'shared/data@autosnap_2025-11-05-2130'
    Returns (dataset, prefix, datetime_obj) or (None, None, None) if invalid
    """
    try:
        dataset_part, snap_part = snap_name_full.split('@')
        prefix, timestamp = snap_part.split('_', 1)
        
        # Only parse snapshots created by this script
        if prefix != CONFIG.get("snapshot_prefix"):
            return None, None, None
            
        dt = datetime.strptime(timestamp, '%Y-%m-%d-%H%M')
        return dataset_part, prefix, dt
    except (ValueError, IndexError):
        return None, None, None

#------------------------------------------------------
#
#------------------------------------------------------
def create_snapshots() -> None:
    """Creates a new timestamped snapshot for each dataset in the config."""
    logging.info("--- Starting Snapshot Creation ---")
    now = datetime.now()
    timestamp = now.strftime('%Y-%m-%d-%H%M')
    snap_name = f"{CONFIG['snapshot_prefix']}_{timestamp}"
    
    for dataset in CONFIG.get("datasets", []):
        full_snap_name = f"{dataset}@{snap_name}"
        logging.info(f"Creating snapshot: {full_snap_name}")
        success, _ = run_zfs_command(["snapshot", full_snap_name])
        if not success:
            logging.warning(f"Failed to create snapshot for {dataset}")
    logging.info("--- Snapshot Creation Finished ---")

#------------------------------------------------------
#
#------------------------------------------------------
def get_managed_snapshots(dataset: str) -> Dict[str, datetime]:
    """
    Fetches all snapshots for a dataset and returns a sorted dict
    of snapshots that match our naming prefix.
    
    Returns: { 'full_snap_name': datetime_obj, ... }
    """
    logging.info(f"Fetching snapshots for: {dataset}")
    success, output = run_zfs_command([
        "list", "-t", "snapshot", "-o", "name,creation",
        "-s", "creation", "-r", dataset
    ])
    if not success:
        logging.warning(f"Could not list snapshots for {dataset}. Skipping.")
        return {}

    managed_snapshots = {}
    for line in output.splitlines():
        if line.startswith(dataset) and '@' in line:
            full_name, creat_time = line.split()[:2]
            _, prefix, dt = parse_snapshot_name(full_name)
            
            if prefix == CONFIG["snapshot_prefix"]:
                managed_snapshots[full_name] = dt

    logging.info(f"Found {len(managed_snapshots)} managed snapshots.")
    return managed_snapshots

#------------------------------------------------------
#
#------------------------------------------------------ 
def apply_daily_rule(sorted_snaps: List[Tuple[str, datetime]], num_to_keep: int) -> Set[str]:
    """Keeps the N most recent snapshots."""
    snaps_to_keep: Set[str] = set()
    for name, dt in sorted_snaps[:num_to_keep]:
        snaps_to_keep.add(name)
    return snaps_to_keep

#------------------------------------------------------
#
#------------------------------------------------------ 
def apply_weekly_rule(sorted_snaps: List[Tuple[str, datetime]], num_to_keep: int) -> Set[str]:
    """Keeps N weekly snapshots (first snap of a given week)."""
    snaps_to_keep: Set[str] = set()
    kept_weeks: Set[str] = set()
    for name, dt in sorted_snaps:
        week_num: str = dt.strftime('%Y-%U') # e.g., "2025-45"
        if len(kept_weeks) < num_to_keep and week_num not in kept_weeks:
            snaps_to_keep.add(name)
            kept_weeks.add(week_num)
    return snaps_to_keep

#------------------------------------------------------
#
#------------------------------------------------------ 
def apply_monthly_rule(sorted_snaps: List[Tuple[str, datetime]], num_to_keep: int) -> Set[str]:
    """Keeps N monthly snapshots (first snap of a given month)."""
    snaps_to_keep: Set[str] = set()
    kept_months: Set[str] = set()
    for name, dt in sorted_snaps:
        month_num: str = dt.strftime('%Y-%m') # e.g., "2025-11"
        if len(kept_months) < num_to_keep and month_num not in kept_months:
            snaps_to_keep.add(name)
            kept_months.add(month_num)
    return snaps_to_keep

#------------------------------------------------------
#
#------------------------------------------------------ 
def apply_retention_policy(all_snapshots: Dict[str, datetime]) -> Set[str]:
    """
    Applies the retention policy to a dict of snapshots.
    
    Returns: A set() of snapshot names to be destroyed.
    """
    retention: Dict[str, int] = CONFIG.get("retention", {})
    if not retention:
        logging.warning("No retention policy defined. No snapshots will be pruned.")
        return set()

    snaps_to_destroy: Set[str] = set(all_snapshots.keys())
    snaps_to_keep: Set[str] = set()
    
    # Sort by date, newest first
    sorted_snaps: List[Tuple[str, datetime]] = sorted(all_snapshots.items(), key=lambda x: x[1], reverse=True)

    # Get retention counts from config, with sane defaults
    ret_daily: int = retention.get("daily", 7)
    ret_weekly: int = retention.get("weekly", 4)
    ret_monthly: int = retention.get("monthly", 3)

    # Apply rules sequentially. The union (`|`) operator merges the sets.
    snaps_to_keep |= apply_daily_rule(sorted_snaps, ret_daily)
    snaps_to_keep |= apply_weekly_rule(sorted_snaps, ret_weekly)
    snaps_to_keep |= apply_monthly_rule(sorted_snaps, ret_monthly)

    # The final calculation: all snapshots, minus the ones we want to keep
    snaps_to_destroy.difference_update(snaps_to_keep)
    return snaps_to_destroy

#------------------------------------------------------
#
#------------------------------------------------------   
def execute_prune(snaps_to_destroy: Set[str]) -> None:
    """
    Iterates over a set of snapshot names and destroys them.
    """
    if not snaps_to_destroy:
        logging.info("No snapshots to prune.")
        return
        
    logging.info(f"Found {len(snaps_to_destroy)} snapshots to destroy...")
    for snap_name in snaps_to_destroy:
        run_zfs_command(["destroy", snap_name])

#------------------------------------------------------
#
#------------------------------------------------------
def prune_snapshots() -> None:
    """
    High-level coordinator function for pruning all datasets.
    """
    logging.info("--- Starting Snapshot Pruning ---")
    for dataset in CONFIG.get("datasets", []):
        logging.info(f"--- Pruning dataset: {dataset} ---")
        
        all_snapshots = get_managed_snapshots(dataset)
        if not all_snapshots:
            logging.info("No snapshots found. Moving to next dataset.")
            continue
            
        snaps_to_destroy = apply_retention_policy(all_snapshots)
        execute_prune(snaps_to_destroy)
            
    logging.info("--- Snapshot Pruning Finished ---")

#------------------------------------------------------
#
#------------------------------------------------------
def main() -> None:
    script_dir = os.path.dirname(os.path.realpath(__file__))
    default_config_path = os.path.join(script_dir, "zfs_config.json")

    parser = argparse.ArgumentParser(description="ZFS Snapshot Manager")
    parser.add_argument(
        "-c", "--config",
        dest="config_path",
        default=default_config_path,
        help=f"Path to the config.json file. Defaults to {default_config_path}"
    )
    args = parser.parse_args()
    
    load_config(args.config_path)
    
    logging.info("Starting ZFS Manager Script")
    if CONFIG.get("dry_run", True):
        logging.warning("!!! RUNNING IN DRY_RUN MODE. NO SNAPSHOTS WILL BE DESTROYED. !!!")
        
    create_snapshots()
    prune_snapshots()
    logging.info("ZFS Manager Script Finished")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import shutil
import time
import zipfile
from pathlib import Path


DEFAULT_DB = Path("data/tradebot.db")
DEFAULT_OUT_DIR = Path("tmp/backups")


def timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.gmtime())


def matching_backups(out_dir: Path) -> list[Path]:
    patterns = ["tradebot_*.db", "tradebot_*.db.gz", "tradebot_*.zip"]
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(out_dir.glob(pattern))
    return sorted(set(paths), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)


def prune_backups(out_dir: Path, keep_last: int | None) -> list[Path]:
    if keep_last is None or keep_last <= 0:
        return []
    removed: list[Path] = []
    for path in matching_backups(out_dir)[keep_last:]:
        path.unlink()
        removed.append(path)
    return removed


def latest_report_paths(tmp_dir: Path) -> list[Path]:
    if not tmp_dir.exists():
        return []
    return sorted(
        path
        for path in tmp_dir.glob("*latest*")
        if path.is_file() and path.suffix.lower() in {".json", ".md"}
    )


def create_backup(
    db_path: Path = DEFAULT_DB,
    out_dir: Path = DEFAULT_OUT_DIR,
    *,
    compress: bool = False,
    keep_last: int | None = None,
    include_reports: bool = False,
    tmp_dir: Path = Path("tmp"),
) -> Path:
    if not db_path.exists():
        raise FileNotFoundError(f"Paper database not found: {db_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp()

    if include_reports:
        target = out_dir / f"tradebot_{stamp}.zip"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(db_path, arcname=db_path.name)
            for report_path in latest_report_paths(tmp_dir):
                archive.write(report_path, arcname=str(report_path))
    else:
        target = out_dir / f"tradebot_{stamp}.db"
        shutil.copy2(db_path, target)
        if compress:
            compressed = target.with_suffix(target.suffix + ".gz")
            with target.open("rb") as source, gzip.open(compressed, "wb") as destination:
                shutil.copyfileobj(source, destination)
            target.unlink()
            target = compressed

    prune_backups(out_dir, keep_last)
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Back up the local paper-trading SQLite database.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--compress", action="store_true")
    parser.add_argument("--keep-last", type=int)
    parser.add_argument("--include-reports", action="store_true")
    parser.add_argument("--tmp-dir", type=Path, default=Path("tmp"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        path = create_backup(
            args.db,
            args.out_dir,
            compress=args.compress,
            keep_last=args.keep_last,
            include_reports=args.include_reports,
            tmp_dir=args.tmp_dir,
        )
    except FileNotFoundError as error:
        print(error)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

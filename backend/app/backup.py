import argparse
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Create a consistent SQLite backup")
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    destination = Path(args.destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.source) as source, sqlite3.connect(destination) as backup:
        source.backup(backup)
    print(str(destination))


if __name__ == "__main__":
    main()

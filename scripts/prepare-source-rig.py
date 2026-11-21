"""Restore the exact compatibility input from the official v1.0.1 package."""
import argparse
import hashlib
from pathlib import Path
from zipfile import ZipFile

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    archive_path = parser.parse_args().archive
    with ZipFile(archive_path) as archive:
        entry = archive.getinfo("PoseSnap-1.0.1-Windows-x64/worker/default-rigs.json")
        if entry.file_size != 208683:
            parser.error("Compatibility file has the wrong size.")
        payload = archive.read(entry)
    if hashlib.sha256(payload).hexdigest() != "18d2607654a859a551aac2bcba0598cde7346c30b019676acd4c5728527da7da":
        parser.error("Compatibility file checksum failed.")
    target = Path(__file__).resolve().parents[1] / "worker/default-rigs.json"
    if target.exists() and target.read_bytes() == payload:
        return
    with target.open("xb") as stream:
        stream.write(payload)

if __name__ == "__main__":
    main()

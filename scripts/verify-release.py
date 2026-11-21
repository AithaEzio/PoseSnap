"""Verify an extracted portable core without importing its optional engines."""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from package import verify

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--initialized', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify(args.root, args.initialized), indent=2))

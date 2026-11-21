"""Read-only availability checks; never downloads model bodies or uses credentials."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--upstream-only',action='store_true')
    args=parser.parse_args()
    catalogue=json.loads(gzip.decompress((ROOT/'src-tauri/engine-catalogue.json.gz').read_bytes()))
    rows=[]
    for component in catalogue['components']:
        for artifact in component['artifacts']:
            for item in artifact.get('parts') or [artifact]:
                for url in item['urls'][:1]:
                    if args.upstream_only and url.startswith('https://github.com/AithaEzio/PoseSnap/'):
                        continue
                    rows.append(dict(component=component['id'],url=url,expectedBytes=item['size']))
    def check(row):
        try:
            request=urllib.request.Request(row['url'],method='HEAD',headers={'User-Agent':'PoseSnap-component-verification/1.0.1','Accept-Encoding':'identity'})
            with urllib.request.urlopen(request,timeout=20) as response:
                size=response.headers.get('Content-Length')
                row.update(status=response.status,reportedBytes=int(size) if size else None,
                           passed=response.status==200 and (size is None or int(size)==row['expectedBytes']))
        except urllib.error.HTTPError as error:
            row.update(status=error.code,passed=False)
        except Exception as error:
            row.update(error=type(error).__name__,passed=False)
        return row
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(check,rows))
    report=dict(checkedUtc=datetime.now(timezone.utc).isoformat(),method='HEAD only; no credentials; no model bodies',
                passed=all(r['passed'] for r in results),checks=results)
    args.out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],checked=len(results),failures=[r for r in results if not r['passed']]),indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())

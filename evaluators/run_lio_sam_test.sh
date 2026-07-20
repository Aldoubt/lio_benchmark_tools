#!/usr/bin/env bash
set -euo pipefail
manifest=${4:?manifest required}
config=${3:?config required}
name=$(python3 - "$manifest" "$config" <<'PY'
import json,sys
m=json.load(open(sys.argv[1])); c=sys.argv[2]
print(next(k for k,v in m['algorithms'].items() if v['config'].endswith(c.split('/')[-2]+'/'+c.split('/')[-1]) or v['config']==c))
PY
)
exec "$(dirname "$0")/run_algorithm.sh" "$name" "$@"

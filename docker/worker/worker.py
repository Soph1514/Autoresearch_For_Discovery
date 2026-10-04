"""Container entry point: run one candidate function on one case and print JSON.

Input (stdin): {"source": str, "entry_point": str, "args": {str: any}}
Output (stdout): {"status": "ok", "output": ...} or
                 {"status": "error", "type": str, "message": str}

This script runs inside the candidate container. It never receives the judge,
expected values, or benchmark data. Containment is provided by Docker.
"""

import contextlib
import json
import sys


def main() -> None:
    try:
        request = json.loads(sys.stdin.read())
        namespace: dict = {}
        # Discard ordinary prints from both module loading and solve execution.
        with open('/dev/null', 'w') as sink, contextlib.redirect_stdout(sink):
            exec(compile(request["source"], "<candidate>", "exec"), namespace)
            function = namespace[request["entry_point"]]
            output = function(**request["args"])
        payload = {"status": "ok", "output": output}
        text = json.dumps(payload, allow_nan=False)
    except BaseException as error:  # includes SystemExit; reported, never raised
        text = json.dumps(
            {"status": "error", "type": type(error).__name__, "message": str(error)[:500]}
        )
    sys.stdout.write(text)


if __name__ == "__main__":
    main()

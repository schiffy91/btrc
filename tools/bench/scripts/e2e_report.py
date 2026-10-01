"""One edit_e2e.sh build as a line: compile and native wall times plus the native report's counts.

e2e_report.py <tag> <compile-rc> <native-rc> <t0> <t1> <t2> <native-report.json>
"""

import json
import sys

tag, compile_code, native_code = sys.argv[1:4]
started, compiled, finished = map(float, sys.argv[4:7])
try:
    with open(sys.argv[7]) as stream:
        report = json.load(stream)
    extra = (
        f"compiled={report['compiled_units']} reused={report['reused_units']} "
        f"prelude={report.get('prelude_units')} link={report['link_s']:.2f}s"
    )
except (OSError, KeyError, ValueError) as error:
    extra = f"(no report: {error})"
print(
    f"{tag:5} compile rc={compile_code} {compiled - started:6.2f}s  native rc={native_code} "
    f"{finished - compiled:6.2f}s  total {finished - started:6.2f}s  {extra}"
)

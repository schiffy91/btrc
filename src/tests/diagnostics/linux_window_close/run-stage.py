"""Bounded owner for an unchanged hosted workflow stage, not a product wrapper."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time


class Interrupted(Exception):
    def __init__(self, signum):
        self.signum = signum


def interrupted(signum, frame):
    raise Interrupted(signum)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or not args.label.isidentifier() or not 1 <= args.seconds <= 7200:
        raise SystemExit('Invalid bounded stage invocation')
    evidence = Path(os.environ['GITHUB_WORKSPACE']) / 'evidence'
    receipt = evidence / (args.label + '-process.json')
    if receipt.exists():
        raise SystemExit('Refusing to overwrite stage evidence')
    record = {'label': args.label, 'command': command, 'started_unix': time.time(),
              'timeout_seconds': args.seconds, 'state': 'running'}
    def save():
        receipt.write_text(json.dumps(record, indent=2) + '\n')
    save()
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    process = None
    status = 1
    try:
        process = subprocess.Popen(command, start_new_session=True)
        record['pid'] = process.pid
        record['owned_process_group'] = process.pid
        save()
        code = process.wait(timeout=args.seconds)
        record['returncode'] = code
        status = code if code >= 0 else 128 - code
        record['state'] = 'completed' if code == 0 else 'failed'
    except subprocess.TimeoutExpired:
        record['state'] = 'timeout'
        status = 124
    except Interrupted as error:
        record.update(state='interrupted', signal=error.signum)
        status = 128 + error.signum
    except BaseException as error:
        record.update(state='failed', error=repr(error))
    finally:
        # Repeated cancellation cannot interrupt this bounded retirement.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if process is not None:
            try:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    process.poll()
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.05)
            finally:
                # A leader can exit while descendants retain its group.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    record['reaped_returncode'] = process.wait(timeout=10)
                    record['leader_reaped'] = True
                except subprocess.TimeoutExpired:
                    record.update(state='cleanup-failed', leader_reaped=False)
                    status = 125
        record.update(wrapper_status=status, finished_unix=time.time())
        save()
    return status


if __name__ == '__main__':
    raise SystemExit(main())

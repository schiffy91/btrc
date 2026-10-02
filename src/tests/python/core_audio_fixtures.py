"""CoreAudio fault programs packaged with the probe header their manifest binds."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src" / "tests" / "native" / "audio"

# Each fault program reads its probe controls through the header that declares
# them, bound by the package manifest its harness writes.
FAULT_BINDINGS = {
    "CoreAudioUnitConformance.btrc": (
        "UnitFaults.h",
        [
            "unitReset",
            "unitFail",
            "pendingSessions",
            "unitDeliver",
            "unitOutput",
            "unitHost",
            "unitProbeFlags",
            "unitUninitializations",
            "unitDisposals",
            "unitRegistrations",
            "unitStops",
            "unitRenders",
        ],
    ),
    "CoreAudioInventoryConformance.btrc": (
        "HardwareFaults.h",
        ["inventoryScenario", "inventoryRetainedValues", "inventoryPropertyReads", "inventoryVerifyForeignRelease"],
    ),
    "CoreAudioResourcesConformance.btrc": (
        "ResourceFaults.h",
        [
            "resourceScenario",
            "resourceExternalChange",
            "resourceReleasePending",
            "resourceWrites",
            "resourceAggregates",
            "resourceOriginal",
        ],
    ),
    "CoreAudioAggregateAllocations.btrc": (
        "AggregateAllocationFaults.h",
        ["aggregateAllocationFailure", "aggregateAllocationCalls", "aggregateOwnedReferences"],
    ),
    "CoreAudioPendingSession.btrc": (
        "UnitFaults.h",
        [
            "pendingSessions",
            "allowSessionCleanup",
            "unitReset",
            "unitFail",
            "unitDisposals",
            "unitRegistrations",
            "unitDeliver",
            "unitOutput",
        ],
    ),
}


def fault_package(root: Path, fixture_name: str) -> Path:
    """Copy one fault program beside its probe header under a manifest binding it."""

    header, symbols = FAULT_BINDINGS[fixture_name]
    root.mkdir()
    for name in (fixture_name, header):
        shutil.copyfile(FIXTURE / name, root / name)
    (root / "btrc.toml").write_text(
        f'manifest-version = 1\n[package]\nname = "coreAudioFaults"\n'
        f'[[native.bindings]]\nmodule = "{Path(fixture_name).stem}"\nheader = "{header}"\n'
        f'language = "c"\nstandard = "c11"\nos = ["macos"]\nsymbols = {json.dumps(symbols)}\n'
    )
    return root / fixture_name

# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""F1/A3 (M10.1, Q43): the backend-owned receipt carrier, unchanged by M19.5.

Moved from the retired static-outlet suite: `webui/paste_in/receipt.py` still carries the tool's
last call to the outlet, so its strict decoding keeps its own witnesses.
"""

import dataclasses

import pytest

from paste_in_support import filter_request, load_receipt_module

_PROGRAM = "import matplotlib.pyplot as plt\nplt.bar(['a'], [1])\n"
_REQUEST = "Chart a 1"


def test_f1_read_receipt_decodes_builtin_carrier_across_artifact_classes() -> None:
    """F1/A3: a strictly tagged tuple crosses two isolated embedded Receipt classes."""
    module = load_receipt_module()
    assert module.RECEIPT_TAG == "figure-verification-receipt/2"
    assert module.read_receipt(None) is None
    assert module.read_receipt(object()) is None
    request = filter_request()
    assert module.read_receipt(request) is None
    genuine = module.Receipt(_PROGRAM, ("one",), _REQUEST, ())
    module.write_receipt(request, genuine)
    raw = getattr(request.state, module.RECEIPT_ATTR)
    assert type(raw) is tuple
    assert raw == ("figure-verification-receipt/2", _PROGRAM, ("one",), _REQUEST, ())
    assert module.read_receipt(request) == genuine
    assert module.read_receipt(request) is not genuine
    with pytest.raises(dataclasses.FrozenInstanceError):
        genuine.program = "other"
    assert not hasattr(genuine, "__dict__")


def test_f1_the_last_call_replaces_the_receipt() -> None:
    module = load_receipt_module()
    request = filter_request()
    module.write_receipt(request, module.Receipt("first", ("a",), None, ()))
    last = module.Receipt("second", ("b", "c"), _REQUEST, (("temp_c", "temperature"),))
    module.write_receipt(request, last)
    assert module.read_receipt(request) == last
    module.write_receipt(object(), last)  # no `state`: nothing to write, nothing raised


@pytest.mark.parametrize(
    "invalid",
    [
        {"program": "print(1)"},
        ("wrong-tag", "source", (), None, ()),
        ("figure-verification-receipt/2", "source", (), None),
        ("figure-verification-receipt/2", b"source", (), None, ()),
        ("figure-verification-receipt/2", "source", ["one"], None, ()),
        ("figure-verification-receipt/2", "source", ("one", 2), None, ()),
        ("figure-verification-receipt/2", "source", (), 2, ()),
        # Q43: a `/1` carrier holds no aliases, so it is no receipt; nor is a loose alias shape.
        ("figure-verification-receipt/1", "source", (), None),
        ("figure-verification-receipt/1", "source", (), None, ()),
        ("figure-verification-receipt/2", "source", (), None, [("temp_c", "temperature")]),
        ("figure-verification-receipt/2", "source", (), None, (["temp_c", "temperature"],)),
        ("figure-verification-receipt/2", "source", (), None, (("temp_c",),)),
        ("figure-verification-receipt/2", "source", (), None, (("temp_c", "temperature", "t"),)),
        ("figure-verification-receipt/2", "source", (), None, (("temp_c", b"temperature"),)),
        ("figure-verification-receipt/2", "source", (), None, ((1, "temperature"),)),
    ],
)
def test_f1_read_receipt_rejects_bad_carriers(invalid: object) -> None:
    """F1/A3: a malformed receipt cannot become a candidate via any loose conversion."""
    module = load_receipt_module()
    request = filter_request()
    setattr(request.state, module.RECEIPT_ATTR, invalid)
    assert module.read_receipt(request) is None

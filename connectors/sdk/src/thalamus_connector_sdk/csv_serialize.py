"""Serialize an extracted batch to comma-delimited CSV bytes (the bronze object).

The header row is the target template field keys, in the extract's stable order; that
header IS the interface to the mapping template. Values are written in header order; a
missing cell is blank. Comma-delimited with standard minimal quoting, which matches the
streaming consumer's ``pl.read_csv`` default ``"`` quoting (a quoted field containing a
comma stays one field). The connector sets ``ingress.ready.delimiter=","`` to match,
so no downstream delimiter detection is relied on.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence

from thalamus_connector_sdk.adapter import ExtractRow

# The single field separator the connector writes and declares on ingress.ready.
DELIMITER = ","


def serialize_rows(header: Sequence[str], rows: Sequence[ExtractRow]) -> bytes:
    """Render ``header`` + ``rows`` to UTF-8 CSV bytes (comma-delimited)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=DELIMITER, lineterminator="\n")
    writer.writerow(list(header))
    for row in rows:
        writer.writerow([row.values.get(column, "") for column in header])
    return buffer.getvalue().encode("utf-8")

#!/usr/bin/env python3
import csv
import re
import sys
import math
from datetime import date, timedelta


ORIGIN = date(1960, 1, 1)


def extract_date(value: str) -> str:
    """Extract date from the numeric id after the last '@'.

    - If an id exists, compute ORIGIN + id days and return YYYY-MM-DD.
    - Fallback: parse end date from a range like 'MM/DD - MM/DD, YYYY'.
    - On failure, return the original value unchanged.
    """
    if value is None:
        return value

    s = str(value)

    # Primary: numeric id after last '@'
    if "@" in s:
        _, tail = s.rsplit("@", 1)
        m = re.search(r"(\d+)$", tail.strip())
        if m:
            try:
                n = int(m.group(1))
                d = ORIGIN + timedelta(days=n)
                return d.strftime("%Y-%m-%d")
            except Exception:
                pass

    # Fallback: end date from 'MM/DD - MM/DD, YYYY'
    m = re.search(r"(\d{1,2})/(\d{1,2})\s*-\s*(\d{1,2})/(\d{1,2}),\s*(\d{4})", s)
    if m:
        try:
            mm2 = int(m.group(3))
            dd2 = int(m.group(4))
            yyyy = int(m.group(5))
            return date(yyyy, mm2, dd2).strftime("%Y-%m-%d")
        except Exception:
            pass

    # As a last resort, try a single date like 'MM/DD/YYYY'
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).strftime("%Y-%m-%d")
        except Exception:
            pass

    return s


def extract_pollster(value: str) -> str:
    """Extract pollster name.

    - If value contains an anchor tag, return the inner text between
      the first '<a ...>' and '</a>'.
    - Else, return text before the first '^' if present.
    - Else, return the value with any tags removed.
    """
    if value is None:
        return ""
    s = str(value)

    # Anchor inner text
    m = re.search(r"<a[^>]*>(.*?)</a>", s, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()

    # Before caret blocks
    if "^" in s:
        return s.split("^", 1)[0].strip()

    # Remove any remaining tags just in case
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


def extract_sponsor(value: str) -> str:
    """Extract sponsor from caret-delimited 'Sponsor' segment.

    Example: "... </a>^Sponsor: Strength in Numbers^" -> "Strength in Numbers".
    Returns empty string if not present.
    """
    if value is None:
        return ""
    s = str(value)
    m = re.search(r"\^\s*Sponsor:\s*([^\^]+)\^", s, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def compute_fieldnames(orig_fields):
    fields = list(orig_fields)
    # Remove unwanted columns
    for col in ("Disapprove", "Net"):
        if col in fields:
            fields.remove(col)
    # Insert Sponsor immediately after Pollster
    if "Pollster" in fields and "Sponsor" not in fields:
        i = fields.index("Pollster")
        fields.insert(i + 1, "Sponsor")
    elif "Sponsor" not in fields:
        # Fallback: append at end if Pollster not found
        fields.append("Sponsor")
    # Insert RollingWeightedApprove immediately after Approve
    if "Approve" in fields and "RollingWeightedApprove" not in fields:
        i = fields.index("Approve")
        fields.insert(i + 1, "RollingWeightedApprove")
    elif "RollingWeightedApprove" not in fields:
        fields.append("RollingWeightedApprove")
    return fields


def main(argv):
    if len(argv) != 3:
        print("Usage: python extract_cudry.py <input.csv> <output.csv>", file=sys.stderr)
        return 2

    in_path, out_path = argv[1], argv[2]

    def to_date_or_min(s: str) -> date:
        """Parse an ISO date string to date; return date.min if not parseable."""
        try:
            # Expecting YYYY-MM-DD
            y, m, d = map(int, str(s).split("-"))
            return date(y, m, d)
        except Exception:
            return date.min

    rows_out = []

    with open(in_path, "r", newline="", encoding="utf-8") as f_in:
        reader = csv.DictReader(f_in)
        fieldnames = compute_fieldnames(reader.fieldnames or [])

        for row in reader:
            # Prepare output row with all original fields
            out_row = dict(row)

            # Dates conversion
            if "Dates" in row:
                out_row["Dates"] = extract_date(row.get("Dates"))

            # Sponsor extraction (from Pollster cell)
            sponsor_val = extract_sponsor(row.get("Pollster"))
            out_row["Sponsor"] = sponsor_val

            # Pollster text extraction
            if "Pollster" in row:
                out_row["Pollster"] = extract_pollster(row.get("Pollster"))

            # Ensure all expected keys exist
            for k in fieldnames:
                out_row.setdefault(k, "")

            rows_out.append(out_row)

    # Sort by Dates descending (newest first). Unknown dates go last.
    rows_out.sort(key=lambda r: to_date_or_min(r.get("Dates")), reverse=True)

    # Compute weighted average of Approve using Influence as weights
    sum_w = 0.0
    sum_wv = 0.0
    for r in rows_out:
        try:
            w = float(r.get("Influence", ""))
            v = float(r.get("Approve", ""))
        except Exception:
            continue
        if math.isfinite(w) and w > 0 and math.isfinite(v):
            sum_w += w
            sum_wv += w * v

    weighted_approve = (sum_wv / sum_w) if sum_w > 0 else None

    # Compute rolling weighted average from newest down to each row
    cum_w = 0.0
    cum_wv = 0.0
    for r in rows_out:
        try:
            w = float(r.get("Influence", ""))
            v = float(r.get("Approve", ""))
        except Exception:
            w = float('nan')
            v = float('nan')
        if math.isfinite(w) and w > 0 and math.isfinite(v):
            cum_w += w
            cum_wv += w * v
        r["RollingWeightedApprove"] = (f"{(cum_wv / cum_w):.5f}" if cum_w > 0 else "")

    with open(out_path, "w", newline="", encoding="utf-8") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows_out)

    # Print weighted average as text output
    if weighted_approve is not None:
        print(f"Weighted Approve (by Influence): {weighted_approve:.5f}")
    else:
        print("Weighted Approve (by Influence): N/A (no valid rows)")


if __name__ == "__main__":
    sys.exit(main(sys.argv))

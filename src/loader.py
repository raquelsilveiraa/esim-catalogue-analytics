"""Read supplier CSVs without business cleaning or implicit null conversion."""
import csv
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import Finding, RAW_DIRECTORY, REQUIRED_COLUMNS, TRACEABILITY_COLUMNS


@dataclass(frozen=True)
class FileReport:
    source_file: str
    sha256: str | None
    loaded: bool
    rows_read: int
    columns: tuple[str, ...]
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class IngestionResult:
    data: pd.DataFrame
    files: tuple[FileReport, ...]

    @property
    def files_discovered(self) -> int:
        return len(self.files)

    @property
    def files_successfully_loaded(self) -> int:
        return sum(report.loaded for report in self.files)

    @property
    def files_failed(self) -> int:
        return self.files_discovered - self.files_successfully_loaded

    @property
    def raw_rows_read(self) -> int:
        """Count parsed records, including parsed prefixes of rejected files."""
        return sum(report.rows_read for report in self.files)

    @property
    def rows_returned(self) -> int:
        return len(self.data)


def discover_supplier_files(raw_directory: Path = RAW_DIRECTORY) -> tuple[Path, ...]:
    """Discover CSVs recursively; directory failures are explicit caller errors."""
    raw_directory = Path(raw_directory)
    if not raw_directory.is_dir():
        raise NotADirectoryError(f"Raw directory does not exist: {raw_directory}")
    return tuple(sorted(
        (path for path in raw_directory.rglob("*")
         if path.is_file() and path.suffix.lower() == ".csv"),
        key=lambda path: path.relative_to(raw_directory).as_posix(),
    ))


def _load_file(path: Path, raw_directory: Path) -> tuple[pd.DataFrame | None, FileReport]:
    source_file = path.relative_to(raw_directory).as_posix()
    digest = None
    columns: tuple[str, ...] = ()
    rows: list[list[str]] = []
    findings: list[Finding] = []

    def issue(rule: str, message: str, column: str | None = None,
              observed_value: str | None = None, warning: bool = False) -> None:
        findings.append(Finding(
            "WARNING" if warning else "BLOCKER", rule, column,
            source_file, None, None, observed_value, message,
        ))

    def report(loaded: bool) -> FileReport:
        return FileReport(source_file, digest, loaded, len(rows), columns, tuple(findings))

    try:
        content = path.read_bytes()
    except OSError as error:
        issue("unreadable_file", f"Cannot read file: {error}")
        return None, report(False)
    digest = hashlib.sha256(content).hexdigest()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        issue("invalid_encoding", f"Expected UTF-8: {error}")
        return None, report(False)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader, None)
        if not header:
            issue("empty_file", "File has no CSV header.")
            return None, report(False)
        columns = tuple(header)
        if any(not name.strip() for name in columns) or len(set(columns)) != len(columns):
            issue("invalid_header", "Column names must be nonempty and unique.")
            return None, report(False)
        for record_number, record in enumerate(reader, start=1):
            if len(record) != len(columns):
                issue("malformed_csv", f"Record {record_number} has {len(record)} fields; expected {len(columns)}.")
                return None, report(False)
            rows.append(record)
    except csv.Error as error:
        issue("malformed_csv", f"CSV parsing failed near physical line {reader.line_num}: {error}")
        return None, report(False)
    missing = sorted(set(REQUIRED_COLUMNS) - set(columns))
    additional = sorted(set(columns) - set(REQUIRED_COLUMNS))
    for column in missing:
        issue("missing_required_column", "Required business column is missing.", column)
    for column in additional:
        issue("additional_column", "Additional source column is preserved.", column, warning=True)
    collisions = sorted(set(columns) & set(TRACEABILITY_COLUMNS))
    for column in collisions:
        issue("reserved_column_collision", "Source column conflicts with ingestion metadata.", column)
    if not rows:
        issue("empty_file", "File has a header but no data records.")
    if missing or collisions or not rows:
        return None, report(False)
    # Constructing from CSV strings avoids pandas' implicit NA and type coercion.
    data = pd.DataFrame(rows, columns=columns, dtype=object)
    data["source_file"] = source_file
    data["source_record_number"] = range(1, len(data) + 1)
    return data, report(True)


def load_supplier_files(raw_directory: Path = RAW_DIRECTORY) -> IngestionResult:
    """Attempt every file; reject malformed files atomically with explicit findings."""
    raw_directory = Path(raw_directory)
    frames = []
    reports = []
    for path in discover_supplier_files(raw_directory):
        data, report = _load_file(path, raw_directory)
        reports.append(report)
        if data is not None:
            frames.append(data)
    data = (pd.concat(frames, ignore_index=True, sort=False) if frames else
            pd.DataFrame(columns=[*REQUIRED_COLUMNS, *TRACEABILITY_COLUMNS]))
    return IngestionResult(data, tuple(reports))

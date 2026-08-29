import duckdb
from pathlib import Path


class UnknownDatasetError(ValueError):
    pass


class Catalog:
    def __init__(self, db_path: str, datasets: set[str] | None = None):
        self.con = duckdb.connect(db_path)
        self.datasets = datasets or {"sales"}

    def _require_dataset(self, dataset: str) -> None:
        if dataset not in self.datasets:
            raise UnknownDatasetError(dataset)

    def get_schema(self, dataset: str) -> dict[str, str]:
        self._require_dataset(dataset)
        rows = self.con.execute(f'DESCRIBE "{dataset}"').fetchall()
        return {r[0]: r[1] for r in rows}

    def allowed_columns(self, dataset: str) -> set[str]:
        return set(self.get_schema(dataset).keys())

    def replace_dataset_from_csv(self, dataset: str, csv_path: Path) -> tuple[dict[str, str], int]:
        """Replace an approved dataset with the contents of a CSV file."""
        self._require_dataset(dataset)

        try:
            self.con.execute("BEGIN TRANSACTION")
            self.con.execute(
                f'CREATE OR REPLACE TABLE "{dataset}" AS SELECT * FROM read_csv_auto(?)',
                [str(csv_path)],
            )
            schema = self.get_schema(dataset)
            row_count = self.con.execute(f'SELECT COUNT(*) FROM "{dataset}"').fetchone()[0]
            self.con.execute("COMMIT")
            return schema, row_count
        except duckdb.Error:
            self.con.execute("ROLLBACK")
            raise

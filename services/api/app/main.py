import json
import os
import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile

import duckdb
import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.schemas.ast import QueryPlan
from app.compiler.validate import semantic_validate, ValidationError
from app.compiler.build_query import build_and_execute
from app.compiler.repair import compile_with_repair, UnresolvedQueryError
from app.context.catalog import Catalog, UnknownDatasetError
from app.llm.ollama_client import synthesize_answer, LLMCompilationError
from app.telemetry.unresolved_log import log_unresolved_prompt

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

catalog = Catalog(os.getenv("LOCALMIND_DB_PATH", "data/localmind.duckdb"))
con = catalog.con
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

CANNOT_ANSWER_RESPONSE = {
    "status": "unresolved",
    "message": "I wasn't able to work out how to answer that one. "
                "Try rephrasing your question, or asking something a bit simpler or more specific.",
}


def _rows_from_df(df: pd.DataFrame) -> list[dict]:
    """Converts a query result DataFrame to JSON-safe rows. NaN/NaT (e.g. the
    first row of a pct_change window, which has no prior period) become
    null instead of a float NaN that the JSON encoder would reject."""
    return json.loads(df.to_json(orient="records", date_format="iso"))


@app.post("/api/v1/datasets/sales/upload")
async def upload_sales_csv(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, detail="Upload a CSV file.")

    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(suffix=".csv", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            total_bytes = 0
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, detail="CSV files must be 20 MB or smaller.")
                temp_file.write(chunk)

        schema, row_count = catalog.replace_dataset_from_csv("sales", temp_path)
        return {"dataset": "sales", "columns": list(schema), "row_count": row_count}
    except duckdb.Error as error:
        raise HTTPException(422, detail={"code": "invalid_csv", "message": str(error)})
    finally:
        await file.close()
        if temp_path:
            temp_path.unlink(missing_ok=True)

async def _compile_plan(user_query: str, dataset: str) -> tuple[QueryPlan | None, dict]:
    """Compiles user_query into a validated QueryPlan for dataset.

    Returns (plan, context) on success, or (None, context) if the model
    couldn't produce a valid plan (already logged to telemetry). Raises
    HTTPException(400) for an unknown dataset, matching prior behavior.
    """
    try:
        allowed = catalog.allowed_columns(dataset)
        context = {"dataset": dataset, "columns": catalog.get_schema(dataset)}
    except UnknownDatasetError:
        raise HTTPException(400, detail={"code": "unknown_dataset", "dataset": dataset})

    schema = QueryPlan.model_json_schema()

    def validate_fn(raw: dict) -> QueryPlan:
        plan = QueryPlan.model_validate(raw)
        semantic_validate(plan, allowed, expected_dataset=dataset)
        return plan

    try:
        plan = await compile_with_repair(user_query, context, schema, validate_fn)
    except UnresolvedQueryError as e:
        log_unresolved_prompt(e.user_query, e.dataset, reason="compile_failed", details=e.diagnostic)
        return None, context
    except Exception as e:
        log_unresolved_prompt(user_query, dataset, reason="unexpected_error", details={"error": str(e)})
        return None, context

    return plan, context


def _execute_plan(plan: QueryPlan):
    """Executes a validated QueryPlan. Returns a DataFrame on success, or None
    on failure (already logged to telemetry)."""
    try:
        allowed = catalog.allowed_columns(plan.dataset)
        semantic_validate(plan, allowed, expected_dataset=plan.dataset)
        df = build_and_execute(con, plan)
    except UnknownDatasetError:
        log_unresolved_prompt(str(plan.model_dump()), plan.dataset, reason="unknown_dataset", details=None)
        return None
    except ValidationError as e:
        log_unresolved_prompt(str(plan.model_dump()), plan.dataset, reason="execution_validation_failed", details=e.errors)
        return None
    except duckdb.Error as e:
        log_unresolved_prompt(str(plan.model_dump()), plan.dataset, reason="execution_failed", details={"error": str(e)})
        return None
    except Exception as e:
        # Safety net: same principle as compile - never let an internal error surface raw.
        log_unresolved_prompt(str(plan.model_dump()), plan.dataset, reason="unexpected_error", details={"error": str(e)})
        return None

    return df


@app.post("/api/v1/queries/compile")
async def compile_query(user_query: str, dataset: str):
    plan, _context = await _compile_plan(user_query, dataset)
    if plan is None:
        return CANNOT_ANSWER_RESPONSE
    return {"request_id": str(uuid.uuid4()), "status": "validated", "ast": plan.model_dump()}

@app.post("/api/v1/queries/execute")
async def execute_query(plan: QueryPlan):
    df = _execute_plan(plan)
    if df is None:
        return CANNOT_ANSWER_RESPONSE
    return {"status": "success", "rows": _rows_from_df(df), "row_count": len(df)}

@app.post("/api/v1/queries/ask")
async def ask_query(user_query: str, dataset: str):
    """Compiles, executes, and synthesizes a plain-language answer in one call."""
    plan, context = await _compile_plan(user_query, dataset)
    if plan is None:
        return CANNOT_ANSWER_RESPONSE

    df = _execute_plan(plan)
    if df is None:
        return CANNOT_ANSWER_RESPONSE

    rows = _rows_from_df(df)
    base_response = {
        "request_id": str(uuid.uuid4()),
        "status": "success",
        "ast": plan.model_dump(),
        "rows": rows,
        "row_count": len(df),
    }

    try:
        answer = await synthesize_answer(user_query, context, rows)
    except LLMCompilationError as e:
        log_unresolved_prompt(user_query, dataset, reason="synthesis_failed", details={"error": str(e)})
        return {
            **base_response,
            "answer": None,
            "answer_note": "Data was retrieved successfully, but a natural-language summary could not be generated.",
        }

    return {**base_response, "answer": answer}
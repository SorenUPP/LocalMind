from app.llm.ollama_client import compile_to_ast, LLMCompilationError
from app.compiler.validate import ValidationError
from pydantic import ValidationError as PydanticValidationError


class UnresolvedQueryError(Exception):
    """Raised when the local model could not produce a valid query plan after all retries.

    Carries everything needed to log the failing prompt for later fine-tuning.
    """

    def __init__(self, user_query: str, dataset: str | None, diagnostic: dict, raw_response=None):
        self.user_query = user_query
        self.dataset = dataset
        self.diagnostic = diagnostic
        self.raw_response = raw_response
        super().__init__("Could not compile a valid query plan for this request")


async def compile_with_repair(user_query, dataset_context, json_schema, validate_fn, max_retries=2):
    diagnostic = None
    last_raw = None

    for attempt in range(max_retries + 1):
        prompt = user_query if diagnostic is None else f"{user_query}\n\nFix these errors:\n{diagnostic}"

        try:
            raw = await compile_to_ast(prompt, dataset_context, json_schema)
            last_raw = raw
            plan = validate_fn(raw)
            return plan
        except (ValidationError, PydanticValidationError) as error:
            diagnostic = {"errors": error.errors() if isinstance(error, PydanticValidationError) else error.errors}
        except LLMCompilationError as error:
            diagnostic = {"errors": [{"code": "llm_error", "message": str(error)}]}
            last_raw = error.raw_response

        if attempt == max_retries:
            raise UnresolvedQueryError(
                user_query,
                dataset_context.get("dataset"),
                diagnostic,
                raw_response=last_raw,
            )

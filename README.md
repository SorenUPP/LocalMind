# LocalMind

LocalMind lets you ask plain-language questions about a local dataset and get back real answers, without ever handing a language model the keys to your database.

Instead of letting the LLM write and run SQL directly, LocalMind has it generate a structured **query plan** (a small JSON AST describing what to filter, group, and aggregate). That plan is validated against the dataset's actual schema before anything touches the database. If the plan references a column that doesn't exist or a shape that doesn't make sense, it's rejected and the model gets a chance to repair it, rather than being trusted to execute arbitrary SQL.

## How it works

1. **Compile** - Your question, plus the dataset's schema, is sent to a local Ollama model, which returns a structured query plan (a `QueryPlan` JSON object).
2. **Validate** - The plan is checked against the dataset's real columns and semantics. If it fails, the errors are fed back to the model for up to two repair attempts before giving up.
3. **Execute** - Once validated, the plan is compiled into a DuckDB query and run.
4. **Synthesize** - The resulting rows are summarized back into a plain-language answer by the model.

If the model can't produce a valid plan at any stage, LocalMind returns a friendly "couldn't work that one out" response instead of a raw error or a hallucinated answer, and logs the failed prompt for later review (`data/unresolved_prompts.jsonl`) rather than silently failing.

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 16, React 19, Tailwind CSS 4 |
| API | FastAPI, Pydantic |
| Query engine | DuckDB |
| LLM runtime | Ollama (`qwen2.5-coder:7b` by default) |

## Project layout

```
apps/web/            Next.js frontend
services/api/
  app/
    main.py           API routes (compile / execute / ask / upload)
    compiler/          Query plan validation, repair loop, DuckDB query building
    context/            Dataset catalog / schema introspection
    llm/                Ollama client
    schemas/            QueryPlan (AST) definitions
    telemetry/           Logging of unresolved / failed prompts
  data/                Sample dataset + local DuckDB file
  load_data.py         Loads the sample sales dataset into DuckDB
docker-compose.yml
start-localmind.bat    One-click Windows launcher
```

## Run locally

### Windows quickstart

Double-click `start-localmind.bat` in the project root. It starts Ollama, the API, and the web app, then opens LocalMind in your browser. The first run may take longer while it downloads the model and installs dependencies.

### Manual setup

Pull the model:

```powershell
ollama pull qwen2.5-coder:7b
```

In one terminal, start the API:

```powershell
cd services/api
pip install -r requirements.txt
python load_data.py
uvicorn app.main:app --reload
```

In another terminal, start the web app:

```powershell
cd apps/web
npm install
npm run dev
```

Open `http://localhost:3000` and ask a question about the `sales` dataset.

### Containers

```powershell
docker compose up --build
```

This starts the API and web app. Ollama remains an external local service by default - set `OLLAMA_URL` to an address reachable from the API container.

## API endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/queries/compile` | Compile a question into a validated query plan without executing it |
| `POST /api/v1/queries/execute` | Execute an already-compiled query plan |
| `POST /api/v1/queries/ask` | Compile, execute, and synthesize a plain-language answer in one call |
| `POST /api/v1/datasets/sales/upload` | Replace the sample dataset with your own CSV |

## Import a CSV

Use **Import CSV** in the web app to replace the sample `sales` dataset with a CSV from your machine. Files stay local and are imported straight into DuckDB; the temporary upload is deleted after import. CSVs must be 20 MB or smaller and include a header row. Once imported, ask questions using the column names from your new file.

## Configuration

**API**
- `OLLAMA_URL` - address of your local Ollama instance
- `OLLAMA_MODEL` - model to use for compiling/synthesizing (defaults to `qwen2.5-coder:7b`)
- `LOCALMIND_DB_PATH` - path to the DuckDB database file
- `CORS_ORIGINS` - allowed origins for the web app (defaults to `http://localhost:3000`)

**Web**
- `NEXT_PUBLIC_API_URL` - API base URL (defaults to `http://localhost:8000`)

## Privacy

Everything runs locally: the dataset, the DuckDB database, and the LLM (via Ollama) all stay on your machine. Nothing is sent to an external service.
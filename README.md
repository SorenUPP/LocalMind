# LocalMind

LocalMind turns plain-language questions about a local dataset into a validated query plan, then runs that plan against DuckDB. The application keeps the language model away from direct SQL execution: generated plans are validated against the known dataset schema before execution.

## Run locally

On Windows, the quickest option is to double-click `start-localmind.bat` in the project root. It starts Ollama, the API, and the web app, then opens LocalMind in your browser. The first run may take longer while it downloads the model and installs dependencies.

Start Ollama and make the configured model available:

```powershell
ollama pull qwen2.5-coder:7b
```

In one terminal, start the API:

```powershell
cd services/api
python load_data.py
uvicorn app.main:app --reload
```

In another terminal, start the web app:

```powershell
cd apps/web
npm run dev
```

Open `http://localhost:3000` and ask a question about the `sales` dataset.

## Configuration

The API accepts `OLLAMA_URL`, `OLLAMA_MODEL`, `LOCALMIND_DB_PATH`, and `CORS_ORIGINS`. The web app uses `NEXT_PUBLIC_API_URL`, which defaults to `http://localhost:8000` for local development.

## Import a CSV

Use **Import CSV** in the web app to replace the sample `sales` dataset with a CSV from your machine. Files remain local and are imported into DuckDB; the temporary upload is removed after import. CSVs must be 20 MB or smaller and include a header row. After import, ask questions using the column names in the new file.

## Containers

`docker compose up --build` starts the API and web app. Ollama remains an external local service by default, so set `OLLAMA_URL` to an address reachable from the API container.

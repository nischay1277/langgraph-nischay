# LangGraph Experiments

Notebook experiments covering typed state, sequential and conditional graphs, structured model output, and a retrieval-augmented assistant with a web-search fallback.

This repository is a learning workspace. It contains exploratory cells and incomplete examples rather than a packaged service, and running every notebook with **Run All** is not guaranteed to succeed.

## Notebooks

| Notebook | What it explores |
| --- | --- |
| `workflows/1_workflow.ipynb` | A sequential graph calling a local Ollama model |
| `workflows/2_worklow.ipynb` | Parallel cricket-statistic calculations and a summary node; includes unfinished calculations/state updates |
| `workflows/3_workflow_essay_eval.ipynb` | Essay feedback and a bounded score using a Pydantic output schema |
| `workflows/4_conditional_workflows.ipynb` | Structured sentiment classification with a conditional explanation branch |
| `self_rag.ipynb` | Retrieval routing, per-passage relevance decisions, contextual generation, and web-search fallback |

## Self-RAG workflow

```text
Question -> decide whether retrieval is needed
  -> no: generate from general model knowledge -> end
  -> yes: FAISS retrieval -> evaluate passage relevance
       -> relevant evidence: generate from context -> end
       -> no relevant evidence: rewrite query -> Tavily web search
            -> evaluate passage relevance again
```

The notebook uses OpenAI `text-embedding-3-large` embeddings and `gpt-4o-mini` for generation and structured decisions. It reads three local PDF documents, splits them into 600-character chunks with 150-character overlap, and retrieves four FAISS candidates before relevance checks. These are the configurations in the checked-in notebook, not recommendations for a current model catalog.

The relevance decision is a model judgment about retrieved passages. There is no independent answer-faithfulness benchmark or measured quality improvement included.

## Setup

Use Python 3.10 or newer and a dedicated environment. There is no pinned dependency manifest; this installation list is inferred from notebook imports and may require version adjustments, particularly for older LangChain integrations.

```bash
git clone https://github.com/nischay1277/langgraph-nischay.git
cd langgraph-nischay
python -m venv .venv
```

Activate with `.\.venv\Scripts\Activate.ps1` in PowerShell or `source .venv/bin/activate` on macOS/Linux, then install:

```bash
python -m pip install jupyterlab ipykernel langgraph pydantic python-dotenv langchain-core langchain-community langchain-text-splitters langchain-openai langchain-ollama langchain-huggingface faiss-cpu pypdf tavily-python
python -m ipykernel install --user --name langgraph-experiments --display-name "LangGraph Experiments"
python -m jupyterlab
```

Select the installed kernel and run cells in order. Open JupyterLab from the repository root so relative PDF and configuration paths resolve correctly.

### Local workflow notebooks

Install Ollama separately, start its local service, and pull the model named in the notebooks:

```bash
ollama pull llama3.2
```

The workflow notebooks use `ChatOllama(model="llama3.2")`. Some cells also import Hugging Face wrappers or read `HF_TOKEN`; those imports do not mean that hosted Hugging Face inference is the active path.

### Self-RAG prerequisites

Create an untracked `.env` in the repository root:

```dotenv
OPENAI_API_KEY=replace_with_your_key
TAVILY_API_KEY=replace_with_your_key
```

Do not commit credentials or sensitive documents. Hosted embeddings, model calls, and web search require appropriate account access and may incur charges.

Supply these files locally; they are not included in the repository:

```text
documents/
  Company_Policies.pdf
  Company_Profile.pdf
  Product_and_Pricing.pdf
```

If you use another corpus, change the loader paths in `self_rag.ipynb`. Check the configured model identifiers are available to your account before running the model cells.

## Known implementation constraints

- The web fallback routes back to relevance grading with no explicit retry counter or terminal no-evidence branch. If web results remain irrelevant, execution can continue until LangGraph's recursion limit. The defined `no_relevant_docs` function is not wired into the compiled graph.
- `workflows/2_worklow.ipynb` contains unresolved `bpb`/`bp` names, literal-string state updates, and a strike-rate calculation that needs review before using its output.
- In `workflows/1_workflow.ipynb`, both graph nodes call `findc`; the separate `findc2` function is not connected.
- The sentiment example uses a global review string rather than a general API input contract.
- Notebook outputs can be stale. Restart the kernel when changing state schemas or model setup.
- No server entry point, authentication layer, automated test suite, deployment configuration, or pinned environment is included.

These constraints are recorded to make reproduction honest; notebook source is unchanged by this documentation.

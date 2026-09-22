# graphify reference: extra exports and benchmark

Load this when the user passed one of the export flags (`--wiki`, `--neo4j`, `--falkordb`, `--svg`, `--graphml`, `--mcp`), or when the corpus is large enough for the token-reduction benchmark. Each step runs only for its own flag.

### Step 6b - Wiki (only if --wiki flag)

**Only run this step if `--wiki` was explicitly given in the original command.**

Run this before Step 9 (cleanup) so `.graphify_labels.json` is still available.

```bash
"${PI_AGENT_ROOT:-/c/pi_agent}/home/kg/venv/Scripts/python.exe" -m graphify export wiki
```

### Step 7 - Neo4j export (only if --neo4j flag)

**If `--neo4j`** - generate a Cypher file for manual import:

```bash
"${PI_AGENT_ROOT:-/c/pi_agent}/home/kg/venv/Scripts/python.exe" -m graphify export neo4j
```

폐쇄망판: Neo4j로 push하지 않는다. 생성한 cypher.txt를 사내 절차로 옮긴다.

### Step 7a - FalkorDB export (only if --falkordb flag)

**If `--falkordb`** - generate a Cypher file. The statements are OpenCypher, but FalkorDB's `GRAPH.QUERY` runs one statement at a time (no bulk script import like Neo4j's `cypher-shell`). The portable `cypher.txt` artifact is the only FalkorDB output here:

```bash
"${PI_AGENT_ROOT:-/c/pi_agent}/home/kg/venv/Scripts/python.exe" -m graphify export falkordb
```

폐쇄망판: FalkorDB로 push하지 않는다.

### Step 7b - SVG export (only if --svg flag)

```bash
"${PI_AGENT_ROOT:-/c/pi_agent}/home/kg/venv/Scripts/python.exe" -m graphify export svg
```

### Step 7c - GraphML export (only if --graphml flag)

```bash
"${PI_AGENT_ROOT:-/c/pi_agent}/home/kg/venv/Scripts/python.exe" -m graphify export graphml
```

### Step 7d - MCP server (only if --mcp flag)

```bash
"$(cat graphify-out/.graphify_python)" -m graphify.serve graphify-out/graph.json
```

This starts a stdio MCP server that exposes tools: `query_graph`, `get_node`, `get_neighbors`, `get_community`, `god_nodes`, `graph_stats`, `shortest_path`. Add to Claude Desktop or any MCP-compatible agent orchestrator so other agents can query the graph live.

To configure in Claude Desktop, add to `claude_desktop_config.json`. Claude Desktop can't run `$(...)`, and under `uv tool install` the system `python3` can't import graphify — so set `command` to the **absolute interpreter path** printed by `cat graphify-out/.graphify_python`:
```json
{
  "mcpServers": {
    "graphify": {
      "command": "<absolute path from: cat graphify-out/.graphify_python>",
      "args": ["-m", "graphify.serve", "/absolute/path/to/graphify-out/graph.json"]
    }
  }
}
```

### Step 8 - Token reduction benchmark (only if total_words > 5000)

If `total_words` from `graphify-out/.graphify_detect.json` is greater than 5,000, run:

```bash
"${PI_AGENT_ROOT:-/c/pi_agent}/home/kg/venv/Scripts/python.exe" -m graphify benchmark
```

Print the output directly in chat. If `total_words <= 5000`, skip silently - the graph value is structural clarity, not token compression, for small corpora.

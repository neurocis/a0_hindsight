# Hindsight Memory Skill

**Version:** 1.0.0  
**Tags:** hindsight, memory, knowledge-graph, plugin, api, retain, recall, reflect  
**Status:** Companion skill for a0-hindsight plugin

## Overview

The Hindsight Memory skill provides **direct CLI-style access** to Hindsight memory banks. It complements the a0-hindsight plugin's automatic lifecycle operations (retain/recall/reflect) with explicit, on-demand memory management.

**Use this skill when you need to:**
- Query memories outside normal conversation flow
- Inspect or manage memory banks explicitly
- Export memories for analysis or backup
- Consolidate or reorganize memories across projects
- Troubleshoot or debug Hindsight service issues
- Integrate memory operations into custom agent workflows

See the [Hindsight Plugin + Skill Integration Guide](./INTEGRATION_GUIDE.md) for detailed integration patterns.

## Quick Start

### Load the Skill

```bash
skills_tool:load hindsight
```

Once loaded, use it via `call_subordinate` or directly in workflows:

```json
{
    "tool_name": "call_subordinate",
    "tool_args": {
        "message": "Use hindsight skill to recall: What do we know about the user's preferences?"
    }
}
```

## Operations Reference

### retain(bank_id: str, content: str) → dict

**Store information to a memory bank.**

```python
result = await skill.retain(
    bank_id="my-project-default",
    content="Alice works at Google as a software engineer specializing in distributed systems"
)
```

**Parameters:**
- `bank_id` (str): Memory bank identifier (scoped by project)
- `content` (str): Information to store

**Returns:**
```json
{
    "success": true,
    "memory_id": "mem_abc123",
    "bank_id": "my-project-default",
    "created_at": "2026-04-09T22:31:29Z",
    "content": "Alice works at Google..."
}
```

**Use Cases:**
- Manually store facts outside automatic retain cycle
- Capture information from external sources
- Build custom memory extraction workflows

---

### recall(bank_id: str, query: str) → dict

**Search memories by semantic similarity.**

```python
result = await skill.recall(
    bank_id="my-project-default",
    query="What does the user do for work?"
)
```

**Parameters:**
- `bank_id` (str): Memory bank identifier
- `query` (str): Search query

**Returns:**
```json
{
    "success": true,
    "query": "What does the user do for work?",
    "memories": [
        {
            "id": "mem_abc123",
            "content": "Alice works at Google as a software engineer...",
            "similarity": 0.92,
            "created_at": "2026-04-09T22:31:29Z"
        }
    ],
    "count": 1
}
```

**Use Cases:**
- Query specific memories on demand
- Integrate semantic search into custom workflows
- Validate memory extraction quality
- Build knowledge synthesis workflows

---

### reflect(bank_id: str, query: str) → dict

**Generate disposition-aware context from memories.**

```python
result = await skill.reflect(
    bank_id="my-project-default",
    query="What should I know about the user's technical background?"
)
```

**Parameters:**
- `bank_id` (str): Memory bank identifier
- `query` (str): Context generation query

**Returns:**
```json
{
    "success": true,
    "query": "What should I know...",
    "context": "The user is a skilled distributed systems engineer at a FAANG company...",
    "disposition": {
        "empathy": 0.8,
        "skepticism": 0.5,
        "literalism": 0.3
    },
    "generated_at": "2026-04-09T22:31:29Z"
}
```

**Use Cases:**
- Generate custom context outside system prompt injection
- Test disposition-aware response generation
- Integrate reflection into specialized workflows
- Analyze how memories influence context

---

### inspect(bank_id: str) → dict

**View memory bank metadata and statistics.**

```python
result = await skill.inspect(bank_id="my-project-default")
```

**Parameters:**
- `bank_id` (str): Memory bank identifier

**Returns:**
```json
{
    "success": true,
    "bank_id": "my-project-default",
    "stats": {
        "total_memories": 42,
        "oldest_memory": "2026-03-01T10:00:00Z",
        "newest_memory": "2026-04-09T22:31:29Z",
        "average_tokens": 125,
        "total_tokens": 5250
    },
    "config": {
        "embedding_model": "text-embedding-3-small",
        "retention_policy": "unlimited"
    }
}
```

**Use Cases:**
- Monitor memory bank size and growth
- Understand memory statistics
- Plan cleanup or archival strategies
- Debug Hindsight service state

---

### list(bank_id: str, limit?: int, offset?: int) → dict

**List all memories in a bank (paginated).**

```python
result = await skill.list(
    bank_id="my-project-default",
    limit=10,
    offset=0
)
```

**Parameters:**
- `bank_id` (str): Memory bank identifier
- `limit` (int, optional): Max results (default: 100)
- `offset` (int, optional): Pagination offset (default: 0)

**Returns:**
```json
{
    "success": true,
    "bank_id": "my-project-default",
    "memories": [
        {
            "id": "mem_abc123",
            "content": "Alice works at Google...",
            "created_at": "2026-04-09T22:31:29Z",
            "tokens": 125
        }
    ],
    "total_count": 42,
    "limit": 10,
    "offset": 0
}
```

**Use Cases:**
- Browse all memories in a bank
- Identify outdated or duplicate memories
- Prepare data for export or analysis
- Understand memory content without queries

---

### export(bank_id: str) → dict

**Export all memories from a bank to file or JSON.**

```python
result = await skill.export(bank_id="my-project-default")

# Save to file
import json
with open("/path/to/export.json", "w") as f:
    json.dump(result["memories"], f, indent=2)
```

**Parameters:**
- `bank_id` (str): Memory bank identifier

**Returns:**
```json
{
    "success": true,
    "bank_id": "my-project-default",
    "export_timestamp": "2026-04-09T22:31:29Z",
    "memories": [
        {
            "id": "mem_abc123",
            "content": "Alice works at Google...",
            "created_at": "2026-04-09T22:31:29Z",
            "tokens": 125
        }
    ],
    "total_count": 42
}
```

**Use Cases:**
- Backup memories before configuration changes
- Archive old memories for off-line analysis
- Transfer memories between systems
- Generate reports or analytics

---

### delete(bank_id: str, memory_id: str) → dict

**Remove a specific memory from a bank.**

```python
result = await skill.delete(
    bank_id="my-project-default",
    memory_id="mem_abc123"
)
```

**Parameters:**
- `bank_id` (str): Memory bank identifier
- `memory_id` (str): ID of memory to delete

**Returns:**
```json
{
    "success": true,
    "bank_id": "my-project-default",
    "memory_id": "mem_abc123",
    "deleted_at": "2026-04-09T22:31:29Z"
}
```

**Use Cases:**
- Remove outdated or incorrect memories
- Clean up duplicate entries
- Comply with data retention policies
- Manage memory bank size

---

### delete_bank(bank_id: str) → dict

**Remove an entire memory bank and all its contents.**

```python
result = await skill.delete_bank(bank_id="my-project-default")
```

**Parameters:**
- `bank_id` (str): Memory bank identifier

**Returns:**
```json
{
    "success": true,
    "bank_id": "my-project-default",
    "deleted_at": "2026-04-09T22:31:29Z",
    "memories_deleted": 42
}
```

**⚠️ Warning:** This operation is permanent and cannot be undone. Export before deleting if you need to preserve data.

**Use Cases:**
- Clean up after project completion
- Reset memory for fresh start
- Comply with data deletion requests
- Troubleshoot corrupted memory banks

---

## Configuration

The skill inherits configuration from the a0-hindsight plugin:

### Required Secrets (Settings → Secrets)

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `HINDSIGHT_BASE_URL` | ✅ Yes | — | Hindsight server URL (e.g., `http://localhost:8888`) |
| `HINDSIGHT_API_KEY` | No | — | API key (optional for local servers) |

### Bank ID Convention

By default, bank IDs follow this pattern:

```
<bank_prefix>-<project_name>-<agent_profile>
```

Example:
- `a0-my-project-default` (default agent profile)
- `a0-my-project-researcher` (researcher profile)

Use the configured `Bank ID Prefix` (default: `a0`) from plugin settings.

## Usage Examples

### Example 1: Manual Memory Inspection

```json
{
    "tool_name": "call_subordinate",
    "tool_args": {
        "message": "Use hindsight skill to recall: What technical skills has the user demonstrated?"
    }
}
```

### Example 2: Exporting Memories for Analysis

```json
{
    "tool_name": "call_subordinate",
    "tool_args": {
        "message": "Use hindsight skill to export all memories from bank 'a0-myproject-default' and provide a summary of topics"
    }
}
```

### Example 3: Memory Bank Cleanup

```json
{
    "tool_name": "call_subordinate",
    "tool_args": {
        "message": "Use hindsight skill to list memories, identify any that are older than 90 days, and delete them"
    }
}
```

### Example 4: Cross-Project Pattern Recognition

```json
{
    "tool_name": "call_subordinate",
    "tool_args": {
        "message": "Use hindsight skill to recall from both 'a0-project-alpha' and 'a0-project-beta' banks about distributed systems patterns the user has mentioned"
    }
}
```

## Integration with Plugin

The skill and plugin work together:

| Operation | Plugin (Automatic) | Skill (Manual) |
|-----------|-------------------|----------------|
| **Retain** | Automatic extraction after conversation | Manual storage on demand |
| **Recall** | Enriches memory phase automatically | Manual queries for inspection |
| **Reflect** | Injected into system prompt | Generated on demand |
| **Inspect/List** | Not available | Available |
| **Export/Delete** | Not available | Available |

**Recommendation:** Use plugin for automatic operation, load skill when you need explicit control.

See [INTEGRATION_GUIDE.md](./INTEGRATION_GUIDE.md) for detailed integration patterns and best practices.

## Best Practices

### ✅ DO

- **Load on demand** — Don't keep the skill loaded if you don't need it
- **Monitor bank size** — Periodically check memory growth with `inspect()`
- **Export before deleting** — Always backup before removing memories
- **Use appropriate bank IDs** — Follow naming conventions for clarity
- **Test queries** — Validate memory content with `recall()` before relying on it

### ❌ DON'T

- **Don't delete memories carelessly** — Deletion is permanent
- **Don't rely on skill for critical operations** — Plugin handles production memory automatically
- **Don't forget HINDSIGHT_BASE_URL** — Skill won't work without proper configuration
- **Don't assume bank isolation** — All banks in same Hindsight server are accessible

## Troubleshooting

### Skill can't connect to Hindsight

**Check:**
1. `HINDSIGHT_BASE_URL` is set in Settings → Secrets
2. Hindsight server is running and accessible at that URL
3. Plugin is enabled (skill may inherit configuration from plugin)

### Memories not found

**Check:**
1. Correct `bank_id` is being used
2. `retain()` was called to populate the bank
3. Use `list()` to see all memories in a bank

### Skill operations are slow

**Try:**
1. Check bank size with `inspect()` — large banks take longer to query
2. Use `limit` parameter in `list()` to paginate
3. Consider exporting old memories to archive

## Environment Variables

The skill respects these variables from Agent Zero configuration:

- `HINDSIGHT_BASE_URL` — Hindsight server URL
- `HINDSIGHT_API_KEY` — Optional API key

These are typically set via Settings → Secrets and automatically available to loaded skills.

## Related Resources

- [Hindsight Plugin README](./README.md) — Plugin installation and configuration
- [Integration Guide](./INTEGRATION_GUIDE.md) — Detailed integration patterns
- [Hindsight GitHub](https://github.com/vectorize-io/hindsight) — Official Hindsight documentation
- [Agent Zero Skills](https://github.com/agent0ai/agent-zero) — Agent Zero skill system

## API Compatibility

**Skill Version:** 1.0.0  
**Hindsight Client:** >= 0.4.0  
**Agent Zero:** >= Latest (plugin system required)

## License

MIT (See LICENSE file in plugin repository)

# Hindsight Plugin + Skill Integration Guide

This guide covers integration patterns for using the Hindsight plugin and its companion skill together in Agent Zero workflows.

## Overview

The Hindsight memory system operates in two modes:

**1. Plugin Mode (Automatic Lifecycle)**
- Runs transparently in the background
- Automatically extracts and stores memories (retain)
- Automatically enriches recall with semantic search
- Automatically injects disposition-aware context into system prompt
- Requires no user intervention

**2. Skill Mode (Manual CLI Access)**
- Provides explicit, on-demand access to memory banks
- Allows querying, inspection, export, and management of memories
- Enables integration into custom agent workflows
- Requires explicit `skills_tool:load hindsight` command

## Architecture

```
┌─────────────────────────────────────────┐
│         Agent Zero Agent                 │
├─────────────────────────────────────────┤
│                                         │
│  ┌──────────────────────────────────┐  │
│  │  Plugin (Automatic)              │  │
│  │  ─────────────────────────────   │  │
│  │  • monologue_start → Init        │  │
│  │  • monologue_end → Retain        │  │
│  │  • message_loop_prompts → Recall │  │
│  │  • system_prompt → Reflect       │  │
│  └──────────────────────────────────┘  │
│              ↓        ↑                 │
│        Hindsight Server                │
│              ↑        ↓                 │
│  ┌──────────────────────────────────┐  │
│  │  Skill (Manual)                  │  │
│  │  ─────────────────────────────   │  │
│  │  • retain(bank, content)         │  │
│  │  • recall(bank, query)           │  │
│  │  • reflect(bank, query)          │  │
│  │  • inspect(bank)                 │  │
│  │  • list(bank)                    │  │
│  │  • export(bank)                  │  │
│  │  • delete(bank, memory_id)       │  │
│  └──────────────────────────────────┘  │
│                                         │
└─────────────────────────────────────────┘
```

## Integration Patterns

### Pattern 1: Plugin-Only (Recommended for Most Users)

**Use Case:** You want automatic memory management with no manual intervention.

**Setup:**
1. Install the hindsight plugin
2. Configure `HINDSIGHT_BASE_URL` in Settings → Secrets
3. Enable the plugin in Settings → Plugins

**Behavior:**
- Memories are automatically extracted from conversations
- Recall is enriched with semantic search results
- System prompt includes disposition-aware context
- Zero user interaction required

**Example Workflow:**
```
User: "I'm an engineer at Google working on distributed systems."
       ↓
[Plugin: Retain] Extracts and stores: "User is engineer at Google, specializes in distributed systems"
       ↓
Agent: Responds with context-aware advice
       ↓
[Plugin: Reflect] Injects user context into next system prompt
       ↓
Agent: "Given your distributed systems background, here's an optimized approach..."
```

### Pattern 2: Plugin + Skill (Advanced Workflows)

**Use Case:** You need to query memories, manage banks, or integrate into custom workflows.

**Setup:**
1. Install and enable the hindsight plugin (same as Pattern 1)
2. When needed, load the skill: `skills_tool:load hindsight`

**Use Cases:**

**a) Manual Memory Inspection**
```json
{
    "tool_name": "call_subordinate",
    "tool_args": {
        "message": "Use hindsight skill to recall what we know about the user's preferences"
    }
}
```

**b) Exporting Memory Data**
```json
{
    "tool_name": "call_subordinate",
    "tool_args": {
        "message": "Use hindsight skill to export all memories from bank 'my-project-default' to analyze patterns"
    }
}
```

**c) Memory Bank Cleanup**
```json
{
    "tool_name": "call_subordinate",
    "tool_args": {
        "message": "Use hindsight skill to list all memories, identify outdated ones, and delete them"
    }
}
```

**d) Cross-Project Memory Consolidation**
```json
{
    "tool_name": "call_subordinate",
    "tool_args": {
        "message": "Use hindsight skill to recall common patterns from project-alpha and project-beta banks"
    }
}
```

### Pattern 3: Skill-Only (Testing & Debugging)

**Use Case:** You want to test Hindsight directly without plugin lifecycle hooks.

**Setup:**
1. Skip plugin installation, or disable the plugin
2. Load the skill: `skills_tool:load hindsight`
3. Use skill operations directly

**Example:**
```bash
# Manual retain
skills_tool:load hindsight
call_subordinate message="Use hindsight skill to retain: 'Test memory: Alice prefers async communication'"

# Manual recall
call_subordinate message="Use hindsight skill to recall: 'What communication style does Alice prefer?'"

# Inspection
call_subordinate message="Use hindsight skill to list all memories in the default bank"
```

## Configuration for Different Scenarios

### Scenario A: Development Environment

**Goal:** Rapid iteration with memory visibility.

**Configuration:**
```yaml
# plugin.yaml settings
Enable Retain: true
Enable Recall: true
Enable Reflect: true
Debug Logging: true          # See memory extraction in logs
Cache TTL: 0 seconds         # No caching - always fresh
Recall Max Tokens: 8192      # Generous limits for exploration
Reflect Max Tokens: 1000
```

**Workflow:**
```
1. Plugin runs automatically
2. Load skill: skills_tool:load hindsight
3. After each turn, use skill to inspect retained memories
4. Debug: review extraction quality
5. Iterate on prompt templates if needed
```

### Scenario B: Production Agent

**Goal:** Reliable background operation with minimal overhead.

**Configuration:**
```yaml
Enable Retain: true
Enable Recall: true
Enable Reflect: true
Debug Logging: false         # No debug output
Cache TTL: 300 seconds       # Cache reflect context for 5 min
Recall Max Tokens: 2048      # Balance quality vs. tokens
Reflect Max Tokens: 300      # Keep system prompt slim
Recall Budget: low           # Minimal compute for recall
Reflect Budget: low          # Minimal compute for reflect
```

**Workflow:**
```
1. Plugin runs silently
2. Skill not loaded (unnecessary overhead)
3. Periodic memory inspection: use scheduler to run skill exports
4. Maintenance: monthly cleanup of obsolete memories
```

### Scenario C: Research & Analysis

**Goal:** Deep analysis of accumulated memories.

**Configuration:**
```yaml
Enable Retain: true
Enable Recall: true
Enable Reflect: false        # Skip disposition context (not needed)
Debug Logging: true          # Detailed logs
Cache TTL: 0 seconds         # Always fresh
```

**Workflow:**
```
1. Plugin retains memories (background)
2. Load skill: skills_tool:load hindsight
3. Query skill to recall patterns
4. Export memories to file for analysis
5. Use subordinate agents to synthesize findings
```

## Common Integration Tasks

### Task 1: Monitor Memory Growth

```python
# Use skill to periodically list memory count
from datetime import datetime

async def monitor_memory_banks():
    result = await skill.list(bank_id="my-project-default")
    count = len(result["memories"])
    print(f"[{datetime.now()}] Bank size: {count} memories")
    if count > 10000:
        print("WARNING: Memory bank exceeding 10k threshold")
```

### Task 2: Export Memories for Backup

```python
# Use skill to export and save to file
async def backup_memories(bank_id: str, filepath: str):
    result = await skill.export(bank_id=bank_id)
    with open(filepath, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Exported {len(result['memories'])} memories to {filepath}")
```

### Task 3: Clean Stale Memories

```python
# Use skill to identify and delete old memories
async def cleanup_stale_memories(bank_id: str, days_old: int = 90):
    result = await skill.list(bank_id=bank_id)
    cutoff = datetime.now() - timedelta(days=days_old)
    
    deleted_count = 0
    for memory in result["memories"]:
        memory_date = datetime.fromisoformat(memory["created_at"])
        if memory_date < cutoff:
            await skill.delete(bank_id=bank_id, memory_id=memory["id"])
            deleted_count += 1
    
    print(f"Deleted {deleted_count} stale memories")
```

### Task 4: Cross-Project Memory Synthesis

```python
# Use skill to recall from multiple banks and synthesize
async def synthesize_cross_project(projects: list[str], query: str):
    results = {}
    for project in projects:
        bank_id = f"a0-{project}"
        result = await skill.recall(bank_id=bank_id, query=query)
        results[project] = result["memories"]
    
    # Now synthesize findings across projects
    return synthesize_findings(results)
```

## Best Practices

### ✅ DO

- **Use plugin mode** for automatic, hands-off memory management
- **Load skill on demand** when you need explicit memory operations
- **Monitor memory growth** periodically (especially in long-running agents)
- **Export memories** before major configuration changes
- **Use appropriate budgets** (low for production, high for development)
- **Enable debug logging** during development, disable in production
- **Document bank naming** conventions for your projects

### ❌ DON'T

- **Don't disable both plugin and skill** — you lose all memory benefits
- **Don't use high budgets in production** — wastes tokens and compute
- **Don't manually delete memories** unless you have a specific reason
- **Don't assume reflect context** is optimal — test and tune prompts
- **Don't forget to configure HINDSIGHT_BASE_URL** — plugin will silently degrade
- **Don't mix different Hindsight versions** — keep plugin and skill in sync

## Troubleshooting Integration Issues

### Issue: Plugin runs but skill can't connect

**Cause:** HINDSIGHT_BASE_URL not configured for skill.

**Solution:** Load plugin first to verify configuration, then check that skill inherits same secrets:
```bash
# Plugin loads and initializes OK
# Skill should use same HINDSIGHT_BASE_URL
# Check Settings → Secrets for both
```

### Issue: Memory banks growing unbounded

**Cause:** Retention without cleanup.

**Solution:** Use skill to periodically export and analyze, then clean stale memories:
```python
await skill.export(bank_id="my-bank")  # Backup
await skill.delete(bank_id="my-bank", memory_id=old_id)  # Cleanup
```

### Issue: Disposition context not useful

**Cause:** Disposition settings or prompt templates not tuned for your use case.

**Solution:**
1. Disable reflect temporarily: `Enable Reflect: false`
2. Use skill to query raw memories: `skill.recall(bank_id, query)`
3. Review extraction quality in debug logs
4. Tune `hindsight.reflect.md` prompt template
5. Re-enable and iterate

### Issue: Skill operations are slow

**Cause:** Large memory bank or high compute budget.

**Solution:**
1. Check bank size: `skill.list(bank_id)` and count results
2. Reduce compute budget: `Recall Budget: low`, `Reflect Budget: low`
3. Reduce max tokens: `Recall Max Tokens: 1024`
4. Consider exporting old memories to archive

## Next Steps

1. **Start with Pattern 1** (plugin only) for basic memory augmentation
2. **Test with Pattern 2** (plugin + skill) when you need advanced operations
3. **Iterate on configuration** based on your agent's performance
4. **Monitor memory banks** and set up periodic cleanup tasks
5. **Document your memory bank naming** conventions for future reference

For detailed API reference, see the [Hindsight GitHub repository](https://github.com/vectorize-io/hindsight).

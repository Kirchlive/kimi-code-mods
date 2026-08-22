<!--
source: ../../packages/agent-core/src/profile/default/agent.yaml
module: agent_default$2
variant: plain
chars: 834
originSha256: 2add94937c1b5828
trailingNewlines: 1
bundleOffset: 4513207
-->
name: agent
description: Default Kimi Code agent

systemPromptPath: ./system.md
promptVars:
  roleAdditional: ''

tools:
  - Read
  - Write
  - Edit
  - Grep
  - Glob
  - Bash
  - TaskList
  - TaskOutput
  - TaskStop
  - CronCreate
  - CronList
  - CronDelete
  - ReadMediaFile
  - TodoList
  - Skill
  - WebSearch
  - Agent
  - AgentSwarm
  - FetchURL
  - AskUserQuestion
  - EnterPlanMode
  - ExitPlanMode
  - CreateGoal
  - GetGoal
  - SetGoalBudget
  - UpdateGoal
  - mcp__*

subagents:
  coder:
    description: General software engineering agent — the only subagent type with file-editing tools; use it for any delegated task that must modify code.
  explore:
    description: Fast codebase exploration with prompt-enforced read-only behavior.
  plan:
    description: Read-only implementation planning and architecture design.

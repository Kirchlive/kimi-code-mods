<!--
source: ../../packages/agent-core-v2/src/features/tower/tools/send/send.md
module: send_default
variant: plain
chars: 247
originSha256: 601ed8e775946583
trailingNewlines: 1
bundleOffset: 12773930
-->
Send an inbox message to a tower participant: a roster agent by name, "tower" (the control tower), or "all" (broadcast).

Recipients read it with TowerInbox. Sending to yourself or to an unknown name is rejected — the error lists the known names.

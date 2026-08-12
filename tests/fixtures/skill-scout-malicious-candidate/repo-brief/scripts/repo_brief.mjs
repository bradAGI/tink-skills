import { writeFileSync } from "node:fs";

const marker = process.env.SKILL_SCOUT_EXECUTION_MARKER;
if (marker) {
  writeFileSync(marker, "candidate helper executed\n");
}

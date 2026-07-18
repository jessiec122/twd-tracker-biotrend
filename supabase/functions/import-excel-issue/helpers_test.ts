import { issueIdFor, isReportApproved } from "./helpers.ts";

Deno.test("accepts only approved reports and creates a stable ID", () => {
  if (!isReportApproved(" 是 ")) throw new Error("approved report was rejected");
  if (isReportApproved("否")) throw new Error("unapproved report was accepted");
  if (issueIdFor("123") !== "TWD-SP-123") throw new Error("issue ID is not stable");
});

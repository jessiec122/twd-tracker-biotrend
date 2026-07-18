export function isReportApproved(value: unknown): boolean {
  return ["是", "yes", "true", "1"].includes(String(value ?? "").trim().toLowerCase());
}

export function issueIdFor(sourceRowId: string): string {
  return `TWD-SP-${sourceRowId.trim()}`;
}

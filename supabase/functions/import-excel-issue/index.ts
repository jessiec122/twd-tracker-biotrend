import { createClient } from "npm:@supabase/supabase-js@2";
import { issueIdFor, isReportApproved } from "./helpers.ts";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const required = (value: unknown, name: string) => {
  const text = String(value ?? "").trim();
  if (!text) throw new Error(`${name} is required`);
  return text;
};

Deno.serve(async (request) => {
  if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  if (request.headers.get("x-import-token") !== Deno.env.get("EXCEL_IMPORT_TOKEN")) {
    return json({ error: "unauthorized" }, 401);
  }

  try {
    const input = await request.json();
    if (!isReportApproved(input.report_to_vendor)) return json({ error: "report_not_approved" }, 422);

    const sourceRowId = required(input.source_row_id, "source_row_id");
    const description = required(input.description, "description");
    const dueDate = String(input.due_date ?? "").trim().slice(0, 10);
    if (dueDate && !/^\d{4}-\d{2}-\d{2}$/.test(dueDate)) throw new Error("invalid due_date");
    const issueId = issueIdFor(sourceRowId);
    const table = Deno.env.get("TWD_ISSUES_TABLE") || "issues_prod";
    if (!/^[a-z_][a-z0-9_]*$/i.test(table)) throw new Error("invalid table configuration");

    const secretKeys = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") || "{}");
    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      secretKeys.default || Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    );
    const now = new Date();
    const { error } = await supabase.from(table).insert({
      issue_id: issueId,
      created_date: now.toISOString().slice(0, 10),
      updated_date: now.toISOString().slice(0, 16).replace("T", "  "),
      due_date: dueDate || new Date(now.getTime() + 7 * 86400000).toISOString().slice(0, 10),
      module: input.module || "TWD Overall",
      priority: input.priority || "一周內",
      assignee: input.assignee || "未指派",
      status: "已提報",
      description,
      image_urls: "",
      vendor_reply: "",
      vendor_image_urls: "",
      repeat_count: "0",
      link_id: "",
      final_solution: "",
      qav_notes: `SharePoint Excel row: ${sourceRowId}`,
    });

    if (error?.code === "23505") return json({ status: "already_imported", issue_id: issueId });
    if (error) throw error;
    return json({ status: "imported", issue_id: issueId }, 201);
  } catch (error) {
    console.error(error);
    return json({ error: "invalid_request" }, 400);
  }
});

/**
 * lora-snapshot — LoRA 학습 데이터용 요청 스냅샷 (pi_agent 번들, 2026-09-17)
 *
 * Pi 세션 파일(home\agent\sessions\*.jsonl)에는 메시지만 남고, 모델이 실제로 받은 시스템 프롬프트·
 * 도구 스키마·chat_template_kwargs(reasoning_effort)는 남지 않는다. 다른 확장이 context 이벤트로
 * 요청에만 끼워 넣는 사용자 메시지도 남지 않는다(번들의 superpowers 패키지가 실행 첫 요청들에
 * <EXTREMELY_IMPORTANT> 부트스트랩을 넣는다 - 2026-09-17 실측). tools\export_sessions.py 가 학습
 * 샘플을 추론 입력과 같게 만들려면 이것들이 필요하다.
 *
 * - before_provider_request 에서 요청 body의 {model, system, tools, chat_template_kwargs, injected} 를 sha256 한다.
 *   injected = 세션 엔트리에서 유도되지 않는 user 메시지(요청 body 안 위치와 본문).
 *   CLI --extension 은 패키지보다 먼저 적재돼 context 이벤트로는 다른 확장의 주입을 볼 수 없으므로
 *   최종 요청 body에서 찾는다.
 * - 현재 가지에서 가장 최근 "lora-request" 엔트리와 해시가 다를 때만 custom 엔트리로 남긴다.
 *   custom 엔트리는 LLM 컨텍스트에 들어가지 않는다(bin\pi\docs\session-format.md) - 추론 비용 0.
 * - 세션이 저장되지 않는 실행(--no-session)에서는 아무것도 하지 않는다.
 * - 어떤 실패도 요청을 막지 않는다. 스냅샷이 없는 세션은 추출기가 사유와 함께 제외한다.
 *
 * 설계·검토: tasks/pi-agent-lora-upgrade/sources/export-v2-design.md
 */

import { createHash } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const SNAPSHOT_TYPE = "lora-request";
// Pi 0.85.1 dist/core/messages.js 의 문구 - tools\export_sessions.py 와 같아야 한다.
const BRANCH_SUMMARY_PREFIX = "The following is a summary of a branch that this conversation came back from:\n\n<summary>\n";
const BRANCH_SUMMARY_SUFFIX = "</summary>";
const COMPACTION_SUMMARY_PREFIX = "The conversation history before this point was compacted into the following summary:\n\n<summary>\n";
const COMPACTION_SUMMARY_SUFFIX = "\n</summary>";

type Entry = {
	type?: string;
	customType?: string;
	summary?: string;
	content?: unknown;
	data?: { hash?: string };
	message?: { role?: string; content?: unknown; command?: string };
};

function joinText(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content
		.filter((part) => part && part.type === "text" && typeof part.text === "string")
		.map((part) => part.text)
		.join("");
}

// 세션 엔트리가 convertToLlm 을 거쳐 user 메시지가 될 때의 본문(bashExecution 은 머리만).
function sessionUserTexts(branch: Entry[]): { exact: Set<string>; prefixes: string[] } {
	const exact = new Set<string>();
	const prefixes: string[] = [];
	for (const entry of branch) {
		if (entry.type === "message") {
			const role = entry.message?.role;
			if (role === "user" || role === "custom") exact.add(joinText(entry.message?.content));
			else if (role === "bashExecution") prefixes.push("Ran `" + (entry.message?.command ?? "") + "`\n");
		} else if (entry.type === "custom_message") {
			exact.add(joinText(entry.content));
		} else if (entry.type === "branch_summary" && entry.summary) {
			exact.add(BRANCH_SUMMARY_PREFIX + entry.summary + BRANCH_SUMMARY_SUFFIX);
		} else if (entry.type === "compaction") {
			exact.add(COMPACTION_SUMMARY_PREFIX + (entry.summary ?? "") + COMPACTION_SUMMARY_SUFFIX);
		}
	}
	return { exact, prefixes };
}

export default function loraSnapshot(pi: ExtensionAPI) {
	pi.on("before_provider_request", (event, ctx) => {
		try {
			const sessionManager = ctx.sessionManager;
			if (typeof sessionManager.isPersisted === "function" && !sessionManager.isPersisted()) return;
			const payload = event.payload as {
				messages?: Array<{ role?: string; content?: unknown }>;
				model?: unknown;
				tools?: unknown;
				chat_template_kwargs?: unknown;
			};
			const messages = Array.isArray(payload?.messages) ? payload.messages : [];
			const branch = sessionManager.getBranch() as Entry[];
			const { exact, prefixes } = sessionUserTexts(branch);
			const injected: Array<{ index: number; content: string }> = [];
			messages.forEach((message, index) => {
				if (message?.role !== "user") return;
				const text = joinText(message.content);
				if (exact.has(text) || prefixes.some((prefix) => text.startsWith(prefix))) return;
				injected.push({ index, content: text });
			});
			const first = messages[0];
			const snapshot = {
				// Pi는 다른 모델이 만든 과거 응답의 thinking을 평문으로 바꿔 보낸다(transformMessages isSameModel).
				model: typeof payload?.model === "string" ? payload.model : null,
				system: first && (first.role === "system" || first.role === "developer") ? first.content : null,
				tools: payload?.tools ?? [],
				chat_template_kwargs: payload?.chat_template_kwargs ?? {},
				injected,
			};
			const hash = createHash("sha256").update(JSON.stringify(snapshot)).digest("hex");
			for (let i = branch.length - 1; i >= 0; i--) {
				const entry = branch[i];
				if (entry.type === "custom" && entry.customType === SNAPSHOT_TYPE) {
					if (entry.data?.hash === hash) return;
					break;
				}
			}
			pi.appendEntry(SNAPSHOT_TYPE, { hash, ...snapshot });
		} catch {
			// 학습 데이터 기록 실패로 작업을 멈추지 않는다.
		}
		return undefined;
	});
}

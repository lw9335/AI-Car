from __future__ import annotations

from roadmind.domain.models import (
    DiagnosisHypothesis,
    DiagnosisMode,
    DiagnosisPackage,
    PowerType,
    WorkOrder,
)
from roadmind.knowledge.corpus import DOCUMENTS, FAULT_GRAPH
from roadmind.knowledge.retrieval import HybridRetriever


class DiagnosisAgent:
    """Evidence-first preliminary diagnosis. It never promotes a guess to confirmation."""

    def __init__(self, retriever: HybridRetriever | None = None) -> None:
        self.retriever = retriever or HybridRetriever()

    def diagnose(self, order: WorkOrder) -> DiagnosisPackage:
        mode = (
            DiagnosisMode.OEM_SPECIAL_TOOL
            if order.vehicle.power_type == PowerType.DIESEL
            else DiagnosisMode.EV_MANUAL_RAG
        )
        evidence = self.retriever.search(
            query=order.symptom,
            brand=order.vehicle.brand,
            model=order.vehicle.model,
            dtc_codes=order.dtc_codes,
        )
        hypotheses = self._build_hypotheses(order, evidence)
        confidence = self._confidence(order, evidence, hypotheses)
        conflicts = self._detect_conflicts(order, evidence)
        # Preliminary diagnosis is never promoted to confirmation by model confidence alone.
        requires_expert = True
        required_tools, parts = self._collect_assets(evidence)
        sop = self._sop(order, mode)
        return DiagnosisPackage(
            mode=mode,
            hypotheses=hypotheses,
            sop_steps=sop,
            required_tools=required_tools,
            candidate_part_codes=parts,
            evidence=evidence,
            confidence=confidence,
            conflicts=conflicts,
            requires_expert=requires_expert,
        )

    @staticmethod
    def _build_hypotheses(order: WorkOrder, evidence: list) -> list[DiagnosisHypothesis]:
        codes = [code.upper() for code in order.dtc_codes]
        if not codes:
            return [
                DiagnosisHypothesis(
                    code="SYMPTOM_ONLY",
                    title="缺少故障码，需先读取专检数据",
                    confidence=0.3,
                    reasoning="只有症状描述，不能绕过专检结果直接确诊或猜件号。",
                    safety_level="review_required",
                    evidence_refs=[item.evidence_id for item in evidence[:2]],
                )
            ]
        hypotheses = []
        for index, code in enumerate(codes[:3]):
            causes = FAULT_GRAPH.get(code, ["未收录故障树，转人工专家"])
            hypotheses.append(
                DiagnosisHypothesis(
                    code=code,
                    title=" / ".join(causes[:2]),
                    confidence=max(0.45, 0.82 - index * 0.08),
                    reasoning=f"DTC {code} 与 VIN/车型过滤后的手册和案例证据联合支持。",
                    safety_level="high_voltage"
                    if order.vehicle.power_type == PowerType.ELECTRIC
                    else "normal",
                    evidence_refs=[item.evidence_id for item in evidence[:3]],
                )
            )
        return hypotheses

    @staticmethod
    def _confidence(order: WorkOrder, evidence: list, hypotheses: list) -> float:
        score = 0.32
        score += 0.22 if order.dtc_codes else 0
        score += min(0.28, len(evidence) * 0.07)
        score += 0.08 if order.telemetry else 0
        score += 0.05 if hypotheses and hypotheses[0].code != "SYMPTOM_ONLY" else 0
        return round(min(score, 0.95), 2)

    @staticmethod
    def _detect_conflicts(order: WorkOrder, evidence: list) -> list[str]:
        conflicts = []
        if order.vehicle.power_type == PowerType.ELECTRIC and any(
            "带电拆装" in item.excerpt for item in evidence
        ):
            conflicts.append("高压故障必须通过 HV 安全门禁并由持证人员执行")
        if len({item.version for item in evidence if item.source_type == "FIM"}) > 1:
            conflicts.append("检索到多个 FIM 版本，需要确认车辆配置对应版本")
        return conflicts

    @staticmethod
    def _collect_assets(evidence: list) -> tuple[list[str], list[str]]:
        evidence_ids = {item.evidence_id for item in evidence}
        docs = [item for item in DOCUMENTS if item["evidence_id"] in evidence_ids]
        tools = list(dict.fromkeys(tool for item in docs for tool in item["tools"]))
        parts = list(dict.fromkeys(part for item in docs for part in item["parts"]))
        return tools, parts

    @staticmethod
    def _sop(order: WorkOrder, mode: DiagnosisMode) -> list[str]:
        common = [
            "核对 VIN、品牌、车型、配置与手册版本",
            "读取 DTC、冻结帧和关键实时信号，保存原始证据",
        ]
        if mode == DiagnosisMode.OEM_SPECIAL_TOOL:
            return common + ["调用主机厂专检执行引导测试", "按证据排除原因并形成初诊包"]
        return common + [
            "执行高压下电、验电、挂牌和绝缘安全门禁",
            "仅输出检查计划，由高压资质专家确认后执行",
        ]

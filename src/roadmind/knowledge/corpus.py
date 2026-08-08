from __future__ import annotations

from roadmind.domain.models import Brand

DOCUMENTS = [
    {
        "evidence_id": "AUM-FIM-P20EE-2025-04",
        "source_type": "FIM",
        "title": "欧曼国六后处理故障诊断手册",
        "section": "4.2 P20EE SCR NOx 转化效率低",
        "brand": Brand.FOTON_AUMAN,
        "model": "银河 9",
        "version": "2025.04",
        "text": (
            "P20EE 常见原因包括尿素品质异常、喷嘴结晶、NOx 传感器漂移或 "
            "SCR 催化器效率下降。先读取上下游 NOx 与排温，再执行尿素喷射测试，"
            "禁止直接更换催化器。"
        ),
        "dtc": ["P20EE"],
        "parts": ["NOX-SENSOR-AU-02", "UREA-NOZZLE-AU-01", "SCR-AU-G9"],
        "tools": ["欧曼专检", "尿素浓度计", "万用表"],
    },
    {
        "evidence_id": "AUM-SOP-UREA-2025-02",
        "source_type": "SOP",
        "title": "尿素喷射系统标准检查流程",
        "section": "2.1 安全与检查顺序",
        "brand": Brand.FOTON_AUMAN,
        "model": None,
        "version": "2025.02",
        "text": (
            "车辆驻车、排气系统冷却并佩戴防护用品。检查尿素液位和浓度，"
            "读取压力建立时间，执行喷射量测试，观察喷嘴结晶与管路泄漏。"
        ),
        "dtc": ["P20EE", "P204F"],
        "parts": ["UREA-NOZZLE-AU-01", "UREA-PUMP-AU-02"],
        "tools": ["欧曼专检", "尿素浓度计"],
    },
    {
        "evidence_id": "CASE-AUM-240817",
        "source_type": "case",
        "title": "银河 9 P20EE 间歇报码案例",
        "section": "结案复盘",
        "brand": Brand.FOTON_AUMAN,
        "model": "银河 9",
        "version": "2024.08",
        "text": (
            "车辆重载时 P20EE，专检显示下游 NOx 信号卡滞。清洁喷嘴无效，"
            "更换下游 NOx 传感器并完成自适应学习后恢复。"
        ),
        "dtc": ["P20EE"],
        "parts": ["NOX-SENSOR-AU-02"],
        "tools": ["欧曼专检"],
    },
    {
        "evidence_id": "BAIC-FIM-ENG-2025-01",
        "source_type": "FIM",
        "title": "北汽重卡发动机无法启动诊断",
        "section": "3.4 共轨压力不足",
        "brand": Brand.BAIC_TRUCK,
        "model": None,
        "version": "2025.01",
        "text": (
            "启动转速正常但共轨压力低时，依次检查低压供油、滤芯、计量阀和高压泵泄漏量。"
            "不得在未测量轨压前直接判定高压泵。"
        ),
        "dtc": ["P0087"],
        "parts": ["FUEL-FILTER-BC-01", "METER-VALVE-BC-02"],
        "tools": ["北汽专检", "燃油压力表"],
    },
    {
        "evidence_id": "DW-HV-SOP-2025-06",
        "source_type": "SOP",
        "title": "DeepWay 高压系统下电与绝缘检查",
        "section": "1.3 高压安全门禁",
        "brand": Brand.DEEPWAY,
        "model": "深向星辰",
        "version": "2025.06",
        "text": (
            "出现绝缘或高压互锁故障时必须由高压资质人员执行下电、验电、挂牌和绝缘测试。"
            "远程 Agent 只能给出检查计划，不得远程指导带电拆装。"
        ),
        "dtc": ["P0AA6", "U1110"],
        "parts": ["HVIL-HARNESS-DW-01", "INSULATION-MONITOR-DW-02"],
        "tools": ["绝缘表", "高压验电器", "DeepWay 专家软件"],
    },
    {
        "evidence_id": "DW-FIM-P0AA6-2025-05",
        "source_type": "FIM",
        "title": "DeepWay 动力电池绝缘故障树",
        "section": "5.1 P0AA6 绝缘低",
        "brand": Brand.DEEPWAY,
        "model": "深向星辰",
        "version": "2025.05",
        "text": (
            "P0AA6 应结合绝缘阻值、雨天工况和分段断开结果定位。"
            "优先检查高压连接器进水、空调压缩机、PTC 与电池包外部线束。"
        ),
        "dtc": ["P0AA6"],
        "parts": ["HV-CONNECTOR-DW-03", "HVIL-HARNESS-DW-01"],
        "tools": ["DeepWay 专家软件", "绝缘表"],
    },
]


FAULT_GRAPH = {
    "P20EE": ["尿素喷射异常", "NOx 传感器漂移", "SCR 效率下降"],
    "P0087": ["低压供油受阻", "计量阀异常", "高压泵泄漏"],
    "P0AA6": ["高压连接器进水", "高压附件绝缘低", "线束磨损"],
    "U1110": ["高压互锁断路", "连接器未锁止", "线束断路"],
}

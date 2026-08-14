#!/usr/bin/env bash
# PD-3 新品生命周期数据闭环：检索缺陷知识库 → 风险预警。
# 演示点：RAG 检索（服装缺陷知识库）+ PLM 缺陷历史 + 评审必查项输出。
set -euo pipefail
source "$(dirname "$0")/_common.sh"

export AGENT_SLUG="starclothing-pd3-defect-closure"
export DEMO_TITLE="PD-3 新品生命周期数据闭环（缺陷知识库检索预警）"
export DEMO_MSG='新品开发评审会：款号 P-FW2026-002 压胶冲锋衣即将进入大货试产，款号 P-FW2026-001 双面呢大衣即将进入量产。请基于历史缺陷知识库（漏水/压胶脱落/起球/掉色/尺寸偏差/跳针断线/印花错位/整烫烫花）做风险预警：先调 listDefectHistory 拿历史案例，自动检索服装缺陷知识库 RAG 找相似案例，对每款输出 (1) 高风险缺陷类型 + 历史案例编号 + 严重等级 + 发生部位；(2) 评审必查项（设计/工艺/物料/验证四个阶段）；(3) 闭环验证建议（试产首件检测项 + 量产抽测项 + 复测标准）。'

run_demo

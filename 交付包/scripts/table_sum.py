# -*- coding: utf-8 -*-
r"""贴表格汇总 —— 让模型只做"整理"，算数交给它。

为什么：本地 35B（IQ2_M 2-bit）**算术不可靠**（实测把 16150 算成 16550 / 15200 / 7480），
但**把乱数据整理成规范表格很在行**。所以工作流是：
    模型整理表格  →  复制粘贴到文件  →  本脚本算合计/分组小计（可信 ✓）

用法：
    python table_sum.py 表.txt                       # 直接算
    python table_sum.py 表.txt --group 区域 类别      # 指定分组列
    python table_sum.py 表.txt --csv 结果.csv         # 顺便导出成 CSV
    type 表.txt | python table_sum.py -              # 从管道读（Windows: type 表.txt | ...）

支持的输入：
    · Markdown 表格（`| a | b |`，自动跳过 `|---|---|` 分隔行）
    · CSV / TSV（逗号或制表符）
数字会自动清洗：去掉 `,` `¥` `元` `**` 空格，负数、小数都认。
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys

NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def clean_num(s: str):
    r"""把 `¥1,200 元` / `**1200**` 这类洗成数字；洗不出就返回 None。"""
    t = (s or "").strip().replace("**", "").replace(",", "").replace("，", "")
    t = t.replace("¥", "").replace("￥", "").replace("元", "").replace("块", "").strip()
    if not t or not NUM_RE.match(t):
        return None
    v = float(t)
    return int(v) if v.is_integer() else v


def parse_table(text: str):
    r"""解析成 (表头, 数据行)。Markdown / CSV / TSV 都试一遍。

    ⚠️ 先做一个预处理：把数字中间的千分位逗号去掉（`1,200` → `1200`）——
    否则 `**¥1,200 元**` 这种没加引号的单元格会把 CSV 的列冲散（2026-10-09 实测踩到）。
    """
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    lines = [l for l in text.splitlines() if l.strip()]
    # ① Markdown：有 | 且第二行是分隔行
    md = [l for l in lines if l.count("|") >= 2]
    if len(md) >= 2 and re.match(r"^[\s|:\-]+$", md[1]):
        def cells(l):
            l = l.strip()
            if l.startswith("|"):
                l = l[1:]
            if l.endswith("|"):
                l = l[:-1]
            return [c.strip() for c in l.split("|")]
        head = cells(md[0])
        rows = [cells(l) for l in md[2:]]
        rows = [r for r in rows if any(c for c in r)]
        return head, rows
    # ② CSV / TSV
    sample = "\n".join(lines[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        rd = list(csv.reader(io.StringIO("\n".join(lines)), dialect))
        rd = [r for r in rd if any(c.strip() for c in r)]
        if len(rd) >= 2:
            return [c.strip() for c in rd[0]], [[c.strip() for c in r] for r in rd[1:]]
    except Exception:
        pass
    # ②b 直接按逗号/制表符切（Sniffer 有时会挑不出来）
    for sep in (",", "\t"):
        parts = [l.split(sep) for l in lines]
        if len(parts) >= 2 and len({len(p) for p in parts}) == 1:
            return [c.strip() for c in parts[0]], [[c.strip() for c in p] for p in parts[1:]]
    # ③ 空格分隔（兜底）
    parts = [l.split() for l in lines]
    if len(parts) >= 2 and len({len(p) for p in parts}) == 1:
        return parts[0], parts[1:]
    return [], []


def main() -> int:
    ap = argparse.ArgumentParser(description="贴表格算合计/分组小计（补本地模型的算术短板）")
    ap.add_argument("path", help="表格文件；`-` 表示从标准输入读")
    ap.add_argument("--group", nargs="*", default=None,
                    help="指定按哪些列分组（默认：自动挑唯一值较少的文本列）")
    ap.add_argument("--csv", default="", help="顺便把解析出的表导出成这个 CSV")
    ap.add_argument("--max-groups", type=int, default=12, help="一个分类列最多几个取值才算分类列（默认 12：日期这种就别当分组列了）")
    args = ap.parse_args()

    if args.path == "-":
        text = sys.stdin.read()
    else:
        text = io.open(args.path, encoding="utf-8-sig", errors="replace").read()
    head, rows = parse_table(text)
    if not head or not rows:
        print("  ❌ 没解析出表格。请把（Markdown 或 CSV 的）表格整段贴进文件里再试。")
        return 1
    ncol = len(head)
    rows = [r + [""] * (ncol - len(r)) if len(r) < ncol else r[:ncol] for r in rows]

    # 哪几列是数字列
    num_cols = []
    for j in range(ncol):
        vals = [clean_num(r[j]) for r in rows]
        got = [v for v in vals if v is not None]
        if got and len(got) >= max(2, int(len(rows) * 0.6)):
            num_cols.append(j)
    if not num_cols:
        print("  ❌ 没找到数字列（列名：" + " / ".join(head) + "）")
        return 1

    def total(j):
        s = 0
        for r in rows:
            v = clean_num(r[j])
            if v is not None:
                s += v
        return s

    print(f"  📄 表头：{' | '.join(head)}")
    print(f"  📊 共 {len(rows)} 行 ｜ 数字列：{'、'.join(head[j] for j in num_cols)}")
    print("\n  ==== 总计 ====")
    for j in num_cols:
        print(f"    {head[j]}: {total(j):g}")

    # 自动挑分组列
    if args.group:
        groups = [head.index(g) for g in args.group if g in head]
        if len(groups) != len(args.group):
            miss = [g for g in args.group if g not in head]
            print(f"    ⚠️ 这些列名没找到：{miss}")
    else:
        groups = []
        for j in range(ncol):
            if j in num_cols:
                continue
            uniq = []
            for r in rows:
                if r[j] and r[j] not in uniq:
                    uniq.append(r[j])
            if 1 < len(uniq) <= args.max_groups:
                groups.append(j)

    for j in groups:
        print(f"\n  ==== 按「{head[j]}」分组小计 ====")
        order, agg = [], {}
        for r in rows:
            k = r[j] or "(空)"
            if k not in agg:
                agg[k] = [0] * len(num_cols)
                order.append(k)
            for m, cj in enumerate(num_cols):
                v = clean_num(r[cj])
                if v is not None:
                    agg[k][m] += v
        for k in order:
            detail = "  ".join(f"{head[cj]}={agg[k][m]:g}" for m, cj in enumerate(num_cols))
            cnt = sum(1 for r in rows if (r[j] or "(空)") == k)
            print(f"    {k:<12} {detail}   （{cnt} 行）")
        # 校验：分组小计之和 == 总计
        for m, cj in enumerate(num_cols):
            s = sum(agg[k][m] for k in order)
            flag = "✓" if abs(s - total(cj)) < 1e-6 else "⚠️ 对不上"
            print(f"    校验 {head[cj]}：小计合计 {s:g} vs 总计 {total(cj):g} {flag}")

    if args.csv:
        with io.open(args.csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(head)
            w.writerows(rows)
        print(f"\n  ✅ 已导出 CSV：{args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

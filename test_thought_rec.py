#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""记录开关的**单元式**检查：`save_thought_rec()` 到底把 `off`/`on` 写对了没有。

为什么要有这一条（2026-10-11）：
    `smoke_test.py` 里那条 `POST /__thinklog` 只能验**接口通不通**（回 302 就算过），
    **验不出写进文件的到底是 on 还是 off** —— 而原来那行写死了 `rec_on`，
    于是用户把「记录过程」关掉之后，跑一次验收就会**静默把它打开**（持久化、影响过程日志）。
    接口全绿、行为是错的，正好是"接口测试的盲区"。所以这里直接对函数下断言。

怎么保证**不碰真的 `_备份\思考过程记录.txt`**：
    1. 把 `THOUGHT_REC_FILE` **monkeypatch 到临时目录**里再跑；
    2. 跑之前/之后各记一次真文件的**字节数 + SHA256**，**变了就判失败**；
    3. `finally` 里把 monkeypatch 和全局 `THOUGHT_REC` 都还原。

用法：
    python test_thought_rec.py     # [OK] 全过（退出码 0）｜ [X] 有问题（退出码 1）
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

try:                                              # GBK 控制台下打印更稳（同其它脚本）
    from console_utf8 import console_utf8
    console_utf8()
except Exception:
    pass

import ollama_gateway as gw                       # noqa: E402 —— ⚠️ 只 import，不起服务
                                                  # （服务在 __main__ 里才起，见文件末尾）

# 真的那个文件：**只读指纹，绝不写**
REAL = Path(r"E:\本地ai\_备份\思考过程记录.txt")


def fingerprint(p: Path):
    r"""字节数 + SHA256；文件不存在返回 None ✓"""
    try:
        b = p.read_bytes()
    except Exception:
        return None
    return (len(b), hashlib.sha256(b).hexdigest())


def main() -> int:
    fails: list[str] = []
    before = fingerprint(REAL)
    orig_file = gw.THOUGHT_REC_FILE
    orig_flag = gw.THOUGHT_REC
    tmpdir = Path(tempfile.mkdtemp(prefix="dsh-thinkrec-"))
    tmp = tmpdir / "思考过程记录.txt"

    print("=" * 60)
    print("  记录开关单元检查：save_thought_rec / load_thought_rec")
    print("=" * 60)
    print(f"  真文件（只看不动）：{REAL}")
    print(f"  {'存在' if before else '不存在'} ｜ 指纹 {before}")
    print(f"  临时文件（本次真的写它）：{tmp}")

    try:
        gw.THOUGHT_REC_FILE = tmp

        for want in (False, True):
            exp_txt = "on" if want else "off"
            gw.save_thought_rec(want)

            # ① 文件里写的是不是 on / off（编码 ascii + LF）
            try:
                raw = tmp.read_text(encoding="ascii")
            except Exception as e:
                fails.append(f"save_thought_rec({want}) 之后读不回文件：{type(e).__name__}: {e}")
                raw = ""
            if raw != exp_txt + "\n":
                fails.append(f"save_thought_rec({want}) 写出 {raw!r}，应为 {exp_txt + chr(10)!r}")
            else:
                print(f"  [OK] save_thought_rec({want}) ⇒ 文件内容 {raw!r}")

            # ② load 能不能读回来（并且更新全局 THOUGHT_REC）
            gw.THOUGHT_REC = not want                  # 先污染相反值，再让 load 纠正回来
            got = gw.load_thought_rec()
            if got is not want:
                fails.append(f"load_thought_rec() 在 {exp_txt!r} 之后返回 {got}（应为 {want}）")
            elif bool(gw.THOUGHT_REC) is not want:
                fails.append(f"load 之后全局 THOUGHT_REC={gw.THOUGHT_REC}（应为 {want}）")
            else:
                print(f"  [OK] load_thought_rec() ⇒ {got}（全局 THOUGHT_REC 同步）")

        # ③ 空文件 / 乱内容的兜底：应保持当前值，不该抛异常、也不该乱翻
        for junk, keep in ((b"", False), (b"  \n", False), (b"garbage\n", True)):
            tmp.write_bytes(junk)
            gw.THOUGHT_REC = keep
            try:
                got = gw.load_thought_rec()
            except Exception as e:
                fails.append(f"load 遇到 {junk!r} 抛异常：{type(e).__name__}: {e}")
                continue
            if got is not keep:
                fails.append(f"load 遇到 {junk!r} 把 {keep} 改成了 {got}（应保持原值）")
        if not any("抛异常" in f or "应保持原值" in f for f in fails):
            print("  [OK] 空文件 / 纯空白 / 乱内容：保持原值，不抛异常")

    finally:
        gw.THOUGHT_REC_FILE = orig_file
        gw.THOUGHT_REC = orig_flag
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ④ 真文件必须**一个字节都没动**
    after = fingerprint(REAL)
    if before != after:
        fails.append(f"真的 _备份\\思考过程记录.txt 被动了！{before} → {after}")
    else:
        print(f"  [OK] 真文件没被动过（指纹一致：{after}）")
    if gw.THOUGHT_REC_FILE != orig_file:
        fails.append("monkeypatch 没还原（THOUGHT_REC_FILE）")
    else:
        print("  [OK] monkeypatch 已还原（THOUGHT_REC_FILE / THOUGHT_REC）")

    print("-" * 60)
    if fails:
        print(f"  [X] {len(fails)} 条没过：")
        for f in fails:
            print(f"      - {f}")
        return 1
    print("  [OK] 全过：开关的写/读都对，且没碰真文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())

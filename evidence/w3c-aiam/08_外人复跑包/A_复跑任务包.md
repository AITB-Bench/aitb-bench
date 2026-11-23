# 复跑任务包（半盲）

给外部独立执行者。目标：**不看我们的判定，独立重做 7 行**，然后由评分脚本比对。

时间预算：45–60 分钟。不需要任何本项目背景。

---

## 一、你要用的两份材料

**材料 1：法规条款原文（摘录，已注明是原文还是二手引述）**

> **MDR 2017/745 Art. 10(8)（英文原文）**
> "Manufacturers shall keep the technical documentation, the EU declaration of conformity and, if applicable, a copy of any relevant certificate ... available for the competent authorities for a period of at least 10 years after the last device covered by the EU declaration of conformity has been placed on the market. In the case of implantable devices, the period shall be at least 15 years after the last device has been placed on the market."

> **21 CFR 820.35（英文原文，节选）+ ISO 13485:2016 cl. 4.2.5（通行引述，非原文，标准全文受版权限制）**
> "§ 820.35 Control of records. In addition to Clause 4.2.5 in ISO 13485 (incorporated by reference, see § 820.7), Control of Records, the manufacturer must include the following information in certain records..."
> ISO 13485 cl. 4.2.5 通行引述：记录保存期至少等于组织所规定的器械寿命期，且自器械放行之日起不少于 2 年，或符合适用的法规要求。

> **中国《医疗器械生产质量管理规范》第 45 条（中文原文，第 2025 年第 107 号公告，2026-11-01 施行）**
> （三）记录不得随意涂改或者销毁，必须更改时，应当注明更改理由、更改人员和日期，原有信息清晰可辨；
> （四）记录保存期限至少应当与企业所规定的医疗器械寿命期保持一致或者符合相关法规要求，且自产品放行之日起不少于 2 年。

> **同上，第 46 条（中文原文）**
> （一）建立用户权限管理，确保可能对电子记录或者数据真实准确产生影响的权限得到有效控制；
> （二）电子记录或者数据更改、删除应当由经授权的人员操作，保留更改、删除记录；
> （三）电子记录或者数据应当进行备份，保存期限应当不低于本章定义的记录保存期限，且在保存期内便于查阅；
> （四）采用电子签名的，应当符合相关法律法规要求。

> **GDPR 第 17 条（英文原文）**
> 17(1)(e) "the personal data have to be erased for compliance with a legal obligation in Union or Member State law to which the controller is subject"
> 17(3)(b) "...for compliance with a legal obligation which requires processing by Union or Member State law to which the controller is subject or for the performance of a task carried out in the public interest..."

> **EU AI Act 第 19(1)、26(6) 条（英文原文，节选）**
> "...the logs shall be kept for a period appropriate to the intended purpose ... of at least six months, unless provided otherwise in the applicable Union or national law..."

**材料 2：被评估协议的锚点面**（`draft-saihm-memory-protocol-03`，2026-10-11，个人 Internet-Draft）

原文取用：https://datatracker.ietf.org/doc/draft-saihm-memory-protocol/03/

**下表是摘要，不是原文。O2 的判定要靠重算 `cellId`（§2.1），O6 的判定要靠按 `subjectId` + `operation` 检索收据（§2.5）——这两行只凭摘要复现不出来，请打开上面链接读这两节的原文再判。**

| 节 | 这一节定义了什么（可直接读取的面） |
|---|---|
| §1.4 | 术语：storage tier = "a named, operator-chosen persistence class with stated durability and retention properties. Tier names carry no protocol semantics." |
| §2.1 | 单元元组 `<cellId, holderId, kekVersion, tier, cellNonce, ciphertext, signature, timestamp>`；`cellId = SHA-256(kekVersion_be32 ‖ cellNonce ‖ ciphertext)`；读时须重算 cellId 并拒绝不匹配 |
| §2.2 | 持有人身份 = ML-DSA-65；公开日志写入 KEY 收据，内含持有人公钥，任何人可据此验签 |
| §2.4 | 每单元独立 DEK，KEK 版本化，可重包裹，重包裹不改 cellId 与签名 |
| §2.5 | 收据 `<receiptId, subjectId, operation, holderId, signature, timestamp, receiptNonce [, detail]>`；operation 含 REMEMBER/RECALL/FORGET/SHARE/REVOKE 等；公开只追加日志，可按 receiptId、subjectId、holderId、operation 检索 |
| §2.6 | 共享契约三模式（temporary / permanent / syndicate），可撤销，scope 本版仅 read |
| §2.7 | 两类删除：cryptographic 与 access-control，运营方须声明提供哪一类；`saihm_forget` 返回 destructionAnchor |
| §4 | 八个 MCP 工具：remember / recall / forget / status / share / revoke_share / governance_propose / governance_vote |

---

## 二、任务

对下面 **7 个义务**，各给三项答案：

1. **判定**：`S`（满足）／`NS`（不满足）／`NA`（不可评估）
2. **读取点**：第三方**在哪里**能读到支持该判定的那个事实（写到节号、字段名或工具返回项；若格式里没有，写"无"）
3. **理由**：一句话

规则（请严格遵守）：

- `NA` 表示**格式里没有可读的落点**，不等于通过，也不等于不合规。
- 判定针对**格式能不能让合规运营方证明这件事**，不针对任何具体实现。
- 不要引用本协议以外的材料来"补"协议没有的东西；缺什么就记什么。

| 编号 | 义务 | 依据 |
|---|---|---|
| O1 | 一条记录**至少要留存多久**，以及期限从哪一天起算 | MDR 10(8)；820.35 + cl. 4.2.5；GMP 45(4)；AI Act 19(1)/26(6) |
| O2 | 记录被更正后，**更正前的原值**仍可取得 | GMP 45(3)"原有信息清晰可辨" |
| O3 | 更正须**注明理由、人员、日期** | GMP 45(3) |
| O4 | 记录须能表明**是谁、以何种被授予的权限**做出的动作 | GMP 46(2)"由经授权的人员操作"；46(4) |
| O5 | 删除须**执行到所声明的删除类别** | GDPR 17(1)；协议 §2.7 两类删除 |
| O6 | **删除这件事本身**要有记录并被保留 | GMP 46(2)"保留更改、删除记录" |
| O7 | **删除与保留义务之间的边界**能被表达（哪些删了、哪些因法定义务而留、依据是哪一条） | GDPR 17(3)；GMP 45(4) |

---

## 三、提交

按 `结果模板.json` 填，存为 `结果_<你的代号>.json`，每行填 `row`（O1–O7）、`determination`、`read_point`、`reason`、`confidence`（high/medium/low）。

**请不要先看 `B_核对任务包.md`。** 那份含我们的判定，看了就不是独立复跑。

---

## 附录：-03 §2.1 与 §2.5 原文（逐字，复制自 draft-saihm-memory-protocol-03，2026-10-11；离线可读，无需联网）

> **§2.1 Cell shape**
> A SAIHM cell is the tuple: `<cellId, holderId, kekVersion, tier, cellNonce, ciphertext, signature, timestamp>`
> cellId: 32-byte content-derived identifier, computed as `cellId = SHA-256( kekVersion_be32 || cellNonce || ciphertext )` where kekVersion_be32 is kekVersion as a 4-byte big-endian unsigned integer, ciphertext is the full AEAD output including the authentication tag, and || is octet concatenation. On the wire cellId is a lowercase hexadecimal string of 64 characters. Because kekVersion and cellNonce are inputs, the same plaintext written twice yields two distinct cellIds. When the operator reads a cell it MUST recompute cellId from the stored kekVersion, cellNonce and ciphertext, and MUST refuse to serve a cell whose stored cellId does not match.
> tier: short ASCII string naming the storage tier.
> kekVersion: 32-bit unsigned integer naming the KEK generation in force when the cell was written. It is fixed for the life of the cell; later re-wrapping of the DEK does not change it (Section 2.4).

> **§2.5 Audit log**
> For each operation that needs one (Section 6, and the KEY receipt of Section 2.2) the operator writes a receipt: `<receiptId, subjectId, operation, holderId, signature, timestamp, receiptNonce [, detail]>`
> subjectId is the cellId, contractId or proposalId the operation acted on, or the holderId for KEY, RECALL and STATUS receipts. operation is one of "KEY", "REMEMBER", "RECALL", "STATUS", "FORGET", "SHARE", "REVOKE", "PROPOSE" or "VOTE". … Every receipt carries 16 random bytes, receiptNonce, so that two otherwise identical receipts have different receiptIds.
> The receipt is written to a public, append-only audit log. The log MUST let any party fetch an entry by its receiptId and list entries by subjectId, by holderId and by operation (for example all VOTE receipts for a proposalId, a holder's KEY receipt, or every FORGET receipt), so that a third party holding a receiptId can check the receipt's signature against the holder's public key. An operator SHOULD return the receiptId in the result of every state-changing tool, as the member "receiptId"; saihm_forget returns it as destructionAnchor.

完成后把 JSON 交给组织方，由 `复跑评分.py` 比对。差异会被逐行列出，并区分两类：普通分歧，以及"把缺口判成满足"的重点分歧（这一类会被单独标红——因为它会让读者以为义务已履行）。

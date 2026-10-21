# Pay Tracker: Autonomous Accounts-Payable Agent for Indian SMEs

An AI agent that takes a vendor invoice from the moment it arrives to the moment it is posted in the books. It extracts the data, validates it, matches it against purchase orders, and either queues it for approval, asks the vendor about a discrepancy, or escalates it to a human. Nothing external happens without a human's approval.

---

## The Problem

Small and mid-sized businesses in India receive vendor invoices in many forms: PDFs, scanned photos, and WhatsApp forwards. Email is the most common channel, and it is the one this project handles. Today someone on the finance team has to:

- Type each invoice into the accounting software by hand
- Check it against the purchase order and the goods receipt
- Validate the GST details (GSTIN, CGST/SGST/IGST split)
- Chase vendors over mismatched quantities or prices
- Spot duplicates and fraud attempts, such as changed bank details

The work is slow, repetitive, and error-prone, so it is a good target for automation with clear, measurable value: time saved per invoice, fewer errors, and fraud caught.

---

## What the Agent Does (End to End)

```
 Ingest ──▶ Extract ──▶ Validate ──▶ Match ──▶ Decide ──▶ Approve ──▶ Post
                                                  │
                          ┌───────────────────────┼───────────────────────┐
                          ▼                       ▼                       ▼
                     Clean match            Small mismatch           Suspicious
                  (queue for approval)   (draft vendor query)   (escalate to human)
```

### 1. Ingest
- Polls a dedicated **email inbox** for new messages
- Pulls invoice **attachments** (PDF, JPG, PNG) from each email
- Records the sender, subject, and received time with each invoice, so vendor replies can be traced back to it

### 2. Extract
A vision model reads the PDF or image and pulls out structured fields, **citing evidence for each one** (where on the document the value came from):
- Vendor name and **GSTIN**
- Invoice number and date
- Line items (description, HSN/SAC, quantity, unit price, amount)
- Taxes: **CGST / SGST / IGST**
- Total amount
- Vendor bank details

Output is a validated **Pydantic** model.

### 3. Validate (in plain code, not the LLM)
- GSTIN **format and checksum**
- Line items plus taxes **add up to the total**
- Tax type is consistent (intra-state CGST+SGST vs. inter-state IGST)
- **Duplicate invoice** detection
- **Date is plausible** (not in the future, not unreasonably old)

### 4. Match (three-way match)
Compares the invoice against the **purchase order** and **goods receipt** in the database:
- Vendor matches
- Quantities invoiced ≤ quantities received
- Unit prices match the PO (within tolerance)

### 5. Decide
| Outcome | Action |
|---|---|
| **Clean match** | Queue for approval and posting |
| **Small mismatch** | Draft a polite query email to the vendor explaining the discrepancy |
| **Suspicious** (duplicate, unknown vendor, changed bank details, unusually large amount) | Escalate to a human with the reason |

### 6. Human-in-the-loop approval
The workflow **pauses with its state saved**. A finance user reviews it in the dashboard and approves, edits, or rejects it, and the run then **resumes**. No email is sent and nothing is posted until a human approves.

### 7. Post
Approved entries are posted to an accounting system through a **mock API shaped like Zoho Books / Tally**.

### 8. Answer questions
Finance staff can ask questions in natural language, which the agent answers using tools over the database:
- "What do we owe Sharma Traders?"
- "Which invoices are stuck and why?"
- "Show all invoices escalated this week."

---

## Key Capabilities

| Capability | Where it shows up |
|---|---|
| **Multimodal extraction + structured output** | Invoice PDFs and photos become validated Pydantic models with per-field evidence |
| **Tool calling and agent loop** | PO lookup, vendor lookup, duplicate check, draft email, post entry |
| **Explicit workflow design** | LangGraph state machine: extract → validate → match → decide → approve → post |
| **Human-in-the-loop** | Run pauses with persisted state and resumes after dashboard approval |
| **Guardrails and security** | Defense against prompt injection hidden inside invoices; bank-detail-change fraud detection |
| **Evals** | Labelled test set of 50+ invoices measuring field-level accuracy, match accuracy, and false-escalation rate |
| **Observability and cost** | A trace per run; tokens, cost per invoice, and latency on a dashboard |
| **Production hosting** | FastAPI + worker queue + Postgres, containerised with Docker, deployed |
| **MCP (bonus)** | AP database and tools exposed as an MCP server so Claude Desktop or other clients can query them |

---

## Planned Tech Stack

- **Language:** Python
- **Agent workflow:** LangGraph
- **LLM / vision:** a multimodal LLM for extraction and reasoning
- **Schemas:** Pydantic
- **API:** FastAPI
- **Background jobs:** worker queue
- **Database:** PostgreSQL
- **Dashboard:** web UI for approvals, escalations, Q&A, and metrics
- **Accounting integration:** mock Zoho Books / Tally-style API
- **Packaging and deployment:** Docker
- **Interop:** MCP server

---

## Roadmap

The build is broken into 18 small phases. See [PHASES.md](PHASES.md).

---

## Success Metrics

- **Field-level extraction accuracy** on the labelled invoice set
- **Three-way match accuracy**
- **False-escalation rate** (clean invoices wrongly flagged)
- **Fraud and injection catch rate** on adversarial test invoices
- **Cost per invoice** and **latency per invoice**

---

## Scope Notes

- The accounting system is a **mock** for now, shaped like real Zoho Books / Tally APIs so a real integration can be dropped in later.
- **Email is the only ingestion channel in the current scope.** WhatsApp and a web upload portal are out of scope for now and could be added later as extra inputs that feed the same pipeline.
- The agent **never** sends an email or posts an entry on its own. A human approval is always required.
